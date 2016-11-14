"""
====================
Constraints checking
====================

Modifies an individual to comply with all constraints

"""
from __future__ import division

import numpy as np
import pandas as pd

import cea.optimization.master.ea.generation as ci
import cea.optimization.supportFn as sFn

__author__ =  "Thuy-An Nguyen"
__copyright__ = "Copyright 2015, Architecture and Building Systems - ETH Zurich"
__credits__ = [ "Thuy-An Nguyen", "Tim Vollrath", "Jimeno A. Fonseca"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "thomas@arch.ethz.ch"
__status__ = "Production"

def manualCheck(individual):
    '''
    Function to manually check the results of a cerain configuration.

    :param individual: list with variables included in each individual.

    :return:
    '''

    # CHP
    individual[0] = 0
    individual[1] = 0
    
    # Base boiler
    individual[2] = 0
    individual[3] = 0
    
    # Peak boiler
    individual[4] = 1
    individual[5] = 1
    
    # HP Lake
    individual[6] = 0
    individual[7] = 0
    
    # Sewage
    individual[8] = 0
    individual[9] = 0
    
    # GHP
    individual[10] = 0
    individual[11] = 0
    
    # HR Data center + Compressed Air
    individual[12] = 0
    individual[13] = 0
    
    # PV
    individual[14] = 0
    individual[15] = 0
    
    # PVT
    individual[16] = 0
    individual[17] = 0
    
    # SC
    individual[18] = 0
    individual[19] = 0
    
    # Total Solar
    individual[20] = 0

    # Buildings
    i = 21
    while i < len(individual):
        individual[i] = 1
        i +=1


def putToRef(individual):
    """
    To used on a population with ONE individual
    Puts that individual to the reference, ie
    All buildings connected to the DHN
    Heating by a centralized pieak boiler
    
    """
    n = len( individual )
    index = 0
    while index < 21:
        individual[index] = 0
        index +=1
    while index < n:
        individual[index] = 1
        index +=1
    individual[4] = 1
    individual[5] = 1   


def GHPCheck(individual, locator, Qnom, gv):
    """
    Computes the geothermal availability and modifies the individual to 
    comply with it
    
    Parameters
    ----------
    individual : list with variables included in each individual.
    locator : path to demand folder
    Qnom : float, Nominal installed capacity in the district heating plant
    
    """
    areaArray = np.array( pd.read_csv(locator.get_geothermal_potential(), usecols=["Area_geo"] ) )
    buildArray = np.array( pd.read_csv(locator.get_geothermal_potential(), usecols=["Name"] ) )
    
    buildList = sFn.extractList(locator.get_total_demand())
    barcode = sFn.individual_to_barcode(individual)
    
    Qallowed = 0

    for index, buildName in zip(barcode, buildList):
        if index == "1":
            areaAvail = areaArray[ np.where(buildArray == buildName)[0][0] ][0]
            Qallowed += np.ceil(areaAvail/gv.GHP_A) * gv.GHP_HmaxSize #[W_th]
    
    print Qallowed, "Qallowed"
    if Qallowed < individual[11] * Qnom:
        print "GHP share modified !"
        
        if Qallowed < 1E-3:
            oldValue = individual[11]
            shareLoss = individual[11]
            individual[10] =0
            individual[11] =0
        
        else:
            oldValue = individual[11]
            shareLoss = oldValue - Qallowed / Qnom
            individual[11] = Qallowed / Qnom
        
        # Adapt the other shares
        nPlant = 0
        for i in range(gv.nHeat - 1):
            if individual[2*i] > 0:
                nPlant += 1
                individual[2*i+1] += individual[2*i+1] * shareLoss / (1-oldValue)
        
        if nPlant == 0: # there was only the GHP --> replaced by only NG Boiler
            individual[2] = 1
            individual[3] = 1-individual[11]

            
def controlCheck(individual, nBuildings, gv):
    """
    check the individual to make sure there are no errors
    
    Parameters
    ----------
    individual : list
    nBuildings : int
        number of buildings   
    
    """
    valid = True
    
    for i in range(gv.nHeat):
        if individual[2*i] > 0 and individual[2*i+1] < 0.01:
            print "Share too low : modified"
            oldValue = individual[2*i+1]
            shareGain = oldValue - 0.01
            individual[2*i+1] = 0.01
            
            for rank in range(gv.nHeat):
                if individual[2*rank] > 0 and i != rank:
                    individual[2*rank + 1] += individual[2*rank + 1] / (1-oldValue) * shareGain
            
    frank = gv.nHeat *2 + gv.nHR
    for i in range(gv.nSolar):
        if individual[frank + 2*i+1] < 0:
            print individual[frank + 2*i+1], "Negative solar share ! Modified"
            individual[frank + 2*i+1] = 0

    sharePlants = 0
    for i in range(gv.nHeat):
        sharePlants += individual[2*i+1]
    if abs(sharePlants - 1) > 1E-3:
        print "Wrong plant share !", sharePlants
        valid = False
    
    shareSolar = 0
    nSol = 0
    for i in range(gv.nSolar):
        nSol += individual[frank + 2*i]
        shareSolar += individual[frank + 2*i+1]
    if nSol > 0 and abs(shareSolar - 1) > 1E-3:
        print "Wrong solar share !", shareSolar
        valid = False
    
    if not valid:       
        print "Non valid individual ! Replace by new one. \n"
        newInd = ci.generateInd(nBuildings, gv)
        
        L = (gv.nHeat + gv.nSolar) * 2 + gv.nHR
        for i in range(L):
            individual[i] = newInd[i]
