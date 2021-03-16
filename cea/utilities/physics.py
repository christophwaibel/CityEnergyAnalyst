# -*- coding: utf-8 -*-
"""
Physical functions
"""
from __future__ import division
import numpy as np

__author__ = "Jimeno A. Fonseca"
__copyright__ = "Copyright 2016, Architecture and Building Systems - ETH Zurich"
__credits__ = ["Jimeno A. Fonseca", "Gabriel Happle"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "cea@arch.ethz.ch"
__status__ = "Production"


def calc_rho_air(temp_air):
    """
    Calculation of density of air according to 6.4.2.1 in [1]

    temp_air : air temperature in (°C)

    rho_air : air density in (kg/m3)

    """
    # constants from Table 12 in [1]
    # TODO import from global variables
    # TODO implement dynamic air density in other functions
    rho_air_ref = 1.23  # (kg/m3)
    temp_air_ref_K = 283  # (K)
    temp_air_K = temp_air + 273  # conversion to (K)

    # Equation (1) in [1]
    rho_air = temp_air_ref_K / temp_air_K * rho_air_ref

    return rho_air


def kelvin_to_fahrenheit(T_Kelvin):
    # converts the temperature from Kelvin to Fahrenheit
    T_Celsius = T_Kelvin - 273.15
    T_Fahrenheit = (T_Celsius*9/5)+32
    return T_Fahrenheit


def calc_wet_bulb_temperature(dry_bulb_temperature, relative_humidity):
    '''
    calc wet bulb temperature from empirical formula in R. Stull, "Wet-Bulb Temperature from Relative Humidity and Air
    Temperature" (2011)
    '''

    return dry_bulb_temperature * np.arctan(0.151977 * (relative_humidity + 8.313659) ** 0.5) + \
           np.arctan(dry_bulb_temperature + relative_humidity) - np.arctan(relative_humidity - 1.676331) + \
           0.00391838 * (relative_humidity) ** 1.5 * np.arctan(0.23101 * relative_humidity) - 4.686035
