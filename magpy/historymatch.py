import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import pickle
from magpy._utils import *

## progress bar
def printProgBar (iteration, total, prefix = '', suffix = '', decimals = 0, length = 20, fill = '█'):
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)

    print('\r%s |%s| %s%% %s' % (prefix, bar, percent, suffix), end = '\r')
    # Print New Line on Complete
    if iteration == total: 
        print()


class Wave:
    """Stores data for wave of HM search."""
    def __init__(self, emuls, zs, cm, var, tests=[]):
        ## passed in
        self.emuls = emuls
        self.zs, self.var, self.cm = zs, var, cm
        self.I, self.pm, self.pv = [], [], []
        self.doneImp = False
        if tests is not []:
            self.setTests(tests)

        self.NIMP = []  # for storing indices of TESTS with Im < cm 
        self.NIMPminmax = {}
        self.NROY = []  # create a design to fill NROY space based of found NIMP points
        self.NROYminmax = {}


    ## pickle a list of relevant data
    def save(self, filename):
        print("= Pickling wave data in", filename, "=")
        w = [ self.TESTS, self.I, self.pm, self.pv, self.NIMP, self.NIMPminmax, self.doneImp, self.NROY, self.NROYminmax ]
        with open(filename, 'wb') as output:
            pickle.dump(w, output, pickle.HIGHEST_PROTOCOL)
        return

    ## unpickle a list of relevant data
    def load(self, filename):
        print("= Unpickling wave data in", filename, "=")
        with open(filename, 'rb') as input:
            w = pickle.load(input)
        self.TESTS, self.I, self.pm, self.pv, self.NIMP, self.NIMPminmax, self.doneImp, self.NROY, self.NROYminmax = [i for i in w]
        return

    ## set the test data
    def setTests(self, tests):
        if isinstance(tests, np.ndarray):
            self.TESTS = tests.astype(np.float16)
            self.I = np.empty((self.TESTS.shape[0],len(self.emuls)),dtype=np.float16)
            self.pm = np.empty((self.TESTS.shape[0],len(self.emuls)),dtype=np.float16)
            self.pv = np.empty((self.TESTS.shape[0],len(self.emuls)),dtype=np.float16)
        else:
            print("ERROR: tests must be a numpy array")
        return


    ## search through the test inputs to find non-implausible points
    def calcImp(self, chunkSize=5000):
        P = self.TESTS[:,0].size
        print("= Calculating Implausibilities of", P, "points =")
        if P > chunkSize:
            chunkNum = int(np.ceil(P / chunkSize))
            print("  Using", chunkNum, "chunks of", chunkSize, "=")
        else:
            chunkNum = 1

        ## loop over outputs (i.e. over emulators)
        printProgBar(0, len(self.emuls)*chunkNum, prefix = '  Progress:', suffix = '')
        for o in range(len(self.emuls)):
            E, z, v = self.emuls[o], self.zs[o], self.var[o]

            for c in range(chunkNum):
                L = c*chunkSize
                U = (c+1)*chunkSize if c < chunkNum -1 else P
                post = E.posteriorPartial(self.TESTS[L:U], predict = True)
                pmean, pvar = post['mean'], post['var'] 
                self.pm[L:U,o] = pmean
                self.pv[L:U,o] = pvar
                self.I[L:U,o] = np.sqrt( ( pmean - z )**2 / ( pvar + v ) )
                printProgBar((o*chunkNum+c+1), len(self.emuls)*chunkNum,
                              prefix = '  Progress:', suffix = '')
 
        self.doneImp = True
        return

    ## recalculate imp using stored pmean and pvar values (presumably user changed z & v
    def recalcImp(self):
        print("\n= Recalculating Implausibilities using stored posterior means and variances =")
        print("█ WARNING: this will be less accurate since posterior only stored as float16")
        for o in range(len(self.emuls)):
            z, v = self.zs[o], self.var[o]
            self.I[:,o] = np.sqrt( ( self.pm[:,o] - z )**2 / ( self.pv[:,o] + v ) )
        return

    ## find all the non-implausible points in the test points
    def findNIMP(self, maxno=1):

        if self.doneImp == False:
            print("ERROR: implausibilities must first be calculated with calcImp()")
            return

        P = self.TESTS[:,0].size
        ## find maximum implausibility across different outputs
        print("  Determining", maxno, "max'th implausibility...")
        Imaxes = np.partition(self.I, -maxno)[:,-maxno]

        ## check cut-off, store indices of points matching condition
        self.NIMP = np.argwhere(Imaxes < self.cm)[:,0]
        percent = ("{0:3.2f}").format(100*float(len(self.NIMP))/float(P))
        print("  NIMP fraction:", percent, "%  (", len(self.NIMP), "points )" )

        ## store minmax of NIMP points along each dimension
        for i in range(self.TESTS.shape[1]):
            NIMPmin = np.amin(self.TESTS[self.NIMP,i])
            NIMPmax = np.amax(self.TESTS[self.NIMP,i])
            self.NIMPminmax[i] = [NIMPmin, NIMPmax]
        #print("  NIMPminmax:", self.NIMPminmax)

        return

    ## fill out NROY space to use as tests for next wave
    def findNROY(self, howMany, maxno=1, factor = 0.1, chunkSize=5000, NROY=False):

        if NROY == False:
            print("= Creating", howMany, "NROY cloud from", self.NIMP.size , "NIMP points =")
            LOC = self.TESTS[self.NIMP]
            dic = self.NIMPminmax
        else:
            print("= Creating", howMany, "NROY cloud from", self.NROY.shape[0], "NROY points =")
            LOC = self.NROY
            dic = self.NROYminmax
        SCALE = np.array( [dic[mm][1]-dic[mm][0] for mm in dic] )
        SCALE = SCALE * factor

        NUM = int(np.ceil( howMany / self.NIMP.shape[0] ))

        print("  Generating (scaled) normal samples within original search range...")
        minmax = self.emuls[0].Data.minmaxScaled
        minlist = [minmax[key][0] for key in minmax]
        maxlist = [minmax[key][1] for key in minmax]
        printProgBar(0, howMany, prefix = '  Progress:', suffix = '')
        NROY = np.zeros([0,self.TESTS.shape[1]])
        condition = True
        while condition:
            ## only original (NIMP or NROY) when findNROY called are used as seeds
            ## this is because those points have already been found to be non-imp
            temp = np.random.normal(loc=LOC, scale=SCALE)

            ## try new method to help with troublesome rands going over minmax range
            minFilter = temp < minlist
            maxFilter = temp > maxlist
            for i in range(temp.shape[0]):
                temp[i,minFilter[i]] = \
                  np.random.normal(loc=LOC[i,minFilter[i]], scale=SCALE[minFilter[i]])
                temp[i,maxFilter[i]] = \
                  np.random.normal(loc=LOC[i,maxFilter[i]], scale=SCALE[maxFilter[i]])

            ## discard values outside of original minmax range here
            minFilter = np.prod( (temp > minlist) , axis=1 )
            maxFilter = np.prod( (temp < maxlist) , axis=1 )
            temp = (temp[minFilter*maxFilter == 1])

            ## add viable points to NROY (tested for imp below)
            NROY = np.concatenate((NROY, temp), axis=0)

            condition = NROY.shape[0] < howMany
            printProgBar(NROY.shape[0] if condition else howMany, howMany,
                         prefix = '  Progress:', suffix = '')

            ## not great method
            ## set values outside of original minmax range to range edge
            #temp = np.random.normal(loc=LOC, scale=SCALE)
            #minFilter = temp < minlist
            #temp[minFilter] = np.repeat([minlist], temp.shape[0], axis=0)[minFilter]
            #maxFilter = temp > maxlist
            #temp[maxFilter] = np.repeat([maxlist], temp.shape[0], axis=0)[maxFilter]
            #NROY = np.concatenate((NROY, temp), axis=0)

        ## hack part 1
        TEMP = [self.TESTS, self.pm, self.pv, self.I, self.NIMP, self.NIMPminmax]

        self.setTests(NROY)
        self.calcImp(chunkSize=chunkSize)
        self.findNIMP(maxno=maxno) # use to get indices of NROY that are imp < cutoff

        self.NROY = np.concatenate( (self.TESTS[self.NIMP], LOC), axis=0 )
        print("  NROY has", self.NROY.shape[0], "points, including original",
              LOC.shape[0], "seed points")

        ## store minmax of NROY points along each dimension
        for i in range(self.NROY.shape[1]):
            NROYmin = np.amin(self.NROY[:,i])
            NROYmax = np.amax(self.NROY[:,i])
            self.NROYminmax[i] = [NROYmin, NROYmax]
        #print("  NROYminmax:", self.NROYminmax)

        ## hack part 2
        [self.TESTS, self.pm, self.pv, self.I, self.NIMP, self.NIMPminmax] = TEMP
        #self.findNIMP() ## ideally I don't want to have to recall this... IS THERE A NEED?

    ## return supplied points in original units
    def unscale(self, points):
        print("= Unscaling points into original units =")
        if points.shape[1] != self.TESTS.shape[1]:
            print("ERROR: features of suppled points and TEST inputs don't match")
            return
        minmax = self.emuls[0].Data.minmax

        ## unscale the points (probably supplied either NIMP subset or NROY subset)
        unscaledPoints = np.empty(points.shape)
        for i in range(points.shape[1]):
            unscaledPoints[:,i] = minmax[i][0] + points[:,i] * (minmax[i][1] - minmax[i][0])
                              
        return unscaledPoints

    ## return supplied points in scaled units
    def scale(self, points):
        print("= Unscaling points into original units =")
        if points.shape[1] != self.TESTS.shape[1]:
            print("ERROR: features of suppled points and TEST inputs don't match")
            return
        minmax = self.emuls[0].Data.minmax

        ## unscale the points (probably supplied either NIMP subset or NROY subset)
        scaledPoints = np.empty(points.shape)
        for i in range(points.shape[1]):
            scaledPoints[:,i] = (points[:,i] - minmax[i][0]) / (minmax[i][1] - minmax[i][0])
                              
        return scaledPoints

## colormaps
def myGrey():
    return '#696988'

def impcolormap():
    return colors.LinearSegmentedColormap.from_list('imp',
      [(0, '#90ff3c'), (0.50, '#ffff3c'), (0.95, '#e2721b'), (1, '#db0100')], N=256)

def odpcolormap():
    #[(0, myGrey()), (0.00000001, '#ffffff'),  # alternative first colours
    cmap = colors.LinearSegmentedColormap.from_list('odp',
      [(0.0, '#ffffff'),
       (0.20, '#93ffff'), (0.45, '#5190fc'), (0.65, '#0000fa'), (1, '#db00fa')], N=256)
    cmap.set_under(color=myGrey())
    return cmap


## implausibility and optical depth plots for all pairs of active indices
def plotImp(wave, maxno=1, grid=10, impMax=None, odpMax=None, linewidths=0.2, filename="hexbin.pkl", points=[], replot=False, colorbar=True, globalColorbar=False, activeId = [], NROY=False):

    print("= Creating History Matching plots =")

    ## option to plot NROY against ODP
    if NROY == True and wave.NROY == []:
        print("█ WARNING: cannot using NROY = True because NROY not calculated")
    if globalColorbar == True and odpMax == None:
        print("█ WARNING: odpMax must be set to use globalColorBar")
    if globalColorbar == True and NROY == True:
        print("█ WARNING: cannot use NROY with globalColorBar")

    ## make list of all the active indices across all emulators
    active = []
    for e in wave.emuls:
        for a in e.Data.active:
            if a not in active: active.append(a)
    active.sort()
    print("  ACTIVE:", active)

    ## restrict to smaller set of active indices
    if activeId != []:
        for a in activeId:
            if a not in active:
                print("ERROR: activeId", a, "not an active emulator index")
                return
        active = activeId
        active.sort()

    ## reference global index into subplot index
    pltRef = {}
    for count, key in enumerate(active): pltRef[key] = count
    print("  PLTREF:", pltRef)

    minmax = wave.emuls[0].Data.minmax

    ## create list of all pairs of active inputs
    gSets = []
    for i in active:
        for j in active:
            if i!=j and i<j and [i,j] not in gSets:  gSets.append([i,j])
    print("  GLOBAL SETS:", gSets)

    if replot == False:

        ## determine the max'th Implausibility
        print("  Determining", maxno, "max'th implausibility...")
        Imaxes = np.partition(wave.I, -maxno)[:,-maxno]

        ## space for all plots, and reference index to subplot indices
        print("  Creating HM plot objects...")
        rc = len(active)
        fig, ax = plt.subplots(nrows = rc, ncols = rc)

        ## set colorbar bounds
        impCB = [0, wave.cm] if impMax == None else [0.0, impMax]
        if odpMax == None and globalColorbar == True:
            print("█ WARNING: cannot use globalColorbar without specifying odpMax for ODP colorbar")
            globalColorbar = False
        odpCB = [0.00000001, None] if odpMax == None else [0.00000001, odpMax]
        #odpCB = [None, None] if odpCB == [] else odpCB

        print("  Making subplots of paired indices...")
        ## loop over plot_bins()
        minCB, maxCB = 1.0, 0.0  ## set backwards here as initial values to be beaten
        printProgBar(0, len(gSets), prefix = '  Progress:', suffix = '')
        for i, s in enumerate(gSets):
            ## minmax is always [0,1] now, so don't need this
            #ex = ( minmax[s[0]][0], minmax[s[0]][1], minmax[s[1]][0], minmax[s[1]][1])
            ex = ( 0,1,0,1 )

            impPlot, odpPlot = ax[pltRef[s[1]],pltRef[s[0]]], ax[pltRef[s[0]],pltRef[s[1]]]

            impPlot.patch.set_facecolor(myGrey())
            if NROY == False or wave.NROY == []:
                im_imp = impPlot.hexbin(
                  wave.TESTS[:,s[0]], wave.TESTS[:,s[1]], C = Imaxes,
                  gridsize=grid, cmap=impcolormap(), vmin=impCB[0], vmax=impCB[1],
                  extent=ex,
                  reduce_C_function=np.min, linewidths=linewidths, mincnt=1)
            else:
                im_imp = impPlot.hexbin(
                  wave.NROY[:,s[0]], wave.NROY[:,s[1]],
                  gridsize=grid, cmap='inferno',
                  extent=ex,
                  linewidths=linewidths, mincnt=1)

            odpPlot.patch.set_facecolor(myGrey())
            im_odp = odpPlot.hexbin(
              wave.TESTS[:,s[0]], wave.TESTS[:,s[1]],
              C = Imaxes<wave.cm,
              #gridsize=grid, bins='log', cmap=odpcolormap(), vmin=odpCB[0], vmax=odpCB[1],
              gridsize=grid, cmap=odpcolormap(), vmin=odpCB[0], vmax=odpCB[1],
              extent=ex,
              linewidths=linewidths, mincnt=1)

            ## save min and max of ODP, useful user info for making global plot
            CBmin, CBmax = np.min(im_odp.get_array()) , np.max(im_odp.get_array())
            if CBmin < minCB:  minCB = CBmin
            if CBmax > maxCB:  maxCB = CBmax

            if globalColorbar == False and colorbar == True:
                plt.colorbar(im_imp, ax=impPlot)
                plt.colorbar(im_odp, ax=odpPlot)

            #impPlot.set_xlabel(minmax[s[0]])
            xlabels = [item.get_text() for item in impPlot.get_xticklabels()]
            ylabels = [item.get_text() for item in impPlot.get_yticklabels()]
            xLabels, yLabels = ['']*len(xlabels), ['']*len(ylabels)
            impPlot.set_xticklabels(xLabels); impPlot.set_yticklabels(yLabels)
            odpPlot.set_xticklabels(xLabels); odpPlot.set_yticklabels(yLabels)
            #impPlot.set_xlabel("sam") 

            printProgBar(i+1, len(gSets), prefix = '  Progress:', suffix = '')

        print("  ODP range:", minCB, ":", maxCB)

        ## global colorbars
        if globalColorbar == True and odpMax != None and NROY == False:
            plt.draw()
            p0 = ax[0,0].get_position().get_points().flatten()
            p1 = ax[rc-1,rc-1].get_position().get_points().flatten()
            # imp
            ax_cbar = fig.add_axes([0.035, p0[0], 0.01, p1[2]-p0[0]])
            plt.colorbar(im_imp, cax=ax_cbar)
            # odp
            ax_cbar = fig.add_axes([p1[2] + 0.045, p0[0], 0.01, p1[2]-p0[0]])
            plt.colorbar(im_odp, cax=ax_cbar)

        ## some plot options
        for a in range(rc):
            fig.delaxes(ax[a,a])

        for a in ax.flat:
            a.set(adjustable='box-forced', aspect='equal')
            #a.set_xticks([]); a.set_yticks([]); a.set_aspect('equal')

        #plt.tight_layout()

    else:
        print("  Unpickling plot in", filename, "...")
        fig, ax = pickle.load(open(filename,'rb'))  # load plot

    pickle.dump([fig, ax], open(filename, 'wb'))  # save plot
    # This is for Python 3 - py2 may need `file` instead of `open`

    ## plots points
    if points is not []:
        print("  Plotting points as well...")
        for p in points:
            for s in gSets:
                ax[pltRef[s[1]],pltRef[s[0]]].scatter(p[s[0]], p[s[1]], s=15, c='black')
                ax[pltRef[s[0]],pltRef[s[1]]].scatter(p[s[0]], p[s[1]], s=15, c='black')

    plt.show()
    return


