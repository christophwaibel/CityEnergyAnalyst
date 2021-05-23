from __future__ import division
import numpy as np
import pandas as pd
import os
from collections import OrderedDict
from cea.utilities.physics import calc_rho_air
from cea.plots.demand.comfort_chart import p_w_from_rh_p_and_ws, p_ws_from_t, hum_ratio_from_p_w_and_p
import cea.osmose.settings as settings
from cea.osmose.auxiliary_functions import calc_h_from_T_w

BUILDINGS_DEMANDS_COLUMNS = ['Name', 'Qww_sys_kWh', 'Qcdata_sys_kWh',
                             'Qcs_sen_ahu_kWh', 'Qcs_sen_aru_kWh', 'Qcs_sen_scu_kWh', 'Qcs_sen_sys_kWh',
                             'Qcs_lat_ahu_kWh', 'Qcs_lat_aru_kWh', 'Qcs_lat_sys_kWh',
                             'Qcs_sys_ahu_kWh', 'Qcs_sys_aru_kWh', 'Qcs_sys_scu_kWh',
                             'people', 'x_int', 'T_int_C', 'T_ext_C']

TSD_COLUMNS = ['T_int', 'T_ext', 'rh_ext', 'w_int', 'x_int', 'x_ve_inf', 'x_ve_mech', 'people', 'I_sol_and_I_rad',
               'Q_gain_lat_peop', 'Q_gain_sen_peop',
               'Q_gain_sen_vent', 'g_dhu_ld', 'm_ve_inf', 'm_ve_mech', 'm_ve_rec', 'm_ve_required', 'm_ve_window']

Q_GAIN_ENV = ['Q_gain_sen_base', 'Q_gain_sen_roof', 'Q_gain_sen_wall', 'Q_gain_sen_wind']

# 'Q_loss_sen_base','Q_loss_sen_roof', 'Q_loss_sen_wall', 'Q_loss_sen_wind']

Q_GAIN_INT = ['Q_gain_sen_app', 'Q_gain_sen_data', 'Q_gain_sen_light', 'Q_gain_sen_pro', 'Q_loss_sen_ref']

TSD_COLUMNS.extend(Q_GAIN_ENV)
TSD_COLUMNS.extend(Q_GAIN_INT)

H_WE_Jperkg = 2466e3  # (J/kg) Latent heat of vaporization of water [section 6.3.6 in ISO 52016-1:2007]
floor_height_m = 2.5  # TODO: read from CEA
v_CO2_Lpers = 0.0048  # [L/s/person]
rho_CO2_kgperm3 = 1.98  # [kg/m3]
CO2_env_ppm = 400 / 1e6  # [m3 CO2/m3]
CO2_ve_min_ppm = 1200 / 1e6  # [m3 CO2/m3]

CO2_room_max_ppm = 900 / 1e6
CO2_room_min_ppm = 400 / 1e6
CO2_room_ppm = 1200 / 1e6

Pair_Pa = 101325
Ra_JperkgK = 286.9
Rw_JperkgK = 461.5

# RH_max = 80  # %
# RH_min = 40  # %
# T_offcoil # TODO: move to config or set as a function
T_low_C = 8.1
T_high_C = 14.1
# T_high_C = 18.1
T_interval = 0.65  # 0.5
# T_low_C = 8.0
# T_high_C = 19.0
# T_interval = 1  # 0.5


N_m_ve_max = 3


# T_low_C = 14.5
# T_high_C = 18
# T_interval = 0.65 #0.5
# SS553_lps_m2 = 0.6


def extract_cea_outputs_to_osmose_main(case, timesteps, season, specified_buildings, problem_type='building'):

    # GET start_t
    start_t, end_t, op_time, periods, timesteps = get_timesteps_info(case, season, timesteps)
    # output to osmose
    output_operatingcost_to_osmose(op_time, timesteps)

    # assumptions according to cases
    RH_max, RH_min = get_RH_limits_assumptions(case)
    w_RA_gperkg = get_humidity_ratio_assumptions(case)

    # read total demand
    total_demand_df = pd.read_csv(path_to_total_demand(case)).set_index('Name')

    # get building names
    if specified_buildings != []:
        building_names = specified_buildings
    else:
        building_names = total_demand_df.index

    # get info from each building
    for building in building_names:
        # get reduced tsd according to the specified timesteps
        reduced_demand_df = get_reduced_demand_df(case, building, end_t, start_t)
        reduced_PV_df = get_reduced_PV_df(case, building, end_t, start_t) # in kWh/m2

        # initializing df
        output_building = pd.DataFrame()
        output_hcs = pd.DataFrame()

        ## output to building.lua
        # de-activate inf when no occupant
        # reduced_demand_df.ix[output_df.people == 0, 'm_ve_inf'] = 0
        output_building['m_ve_inf'] = reduced_demand_df['m_ve_inf']  # kg/s
        ## heat gain
        reduced_demand_df = calc_sensible_gains(reduced_demand_df)
        output_building['Q_gain_total_kWh'] = reduced_demand_df['Q_gain_total_kWh']
        output_building['Q_gain_occ_kWh'] = reduced_demand_df['Q_gain_occ_kWh']
        # output_building['Q_gain_int_kWh'] = reduced_demand_df['Q_gain_int_kWh']
        # output_building['Q_gain_rad_kWh'] = reduced_demand_df['Q_gain_rad_kWh']
        # output_building['Q_gain_env_kWh'] = reduced_demand_df['Q_gain_env_kWh']
        Q_sen_gain_inf_kWh = np.vectorize(calc_Q_sen_gain_inf_kWh)(reduced_demand_df['T_ext'],
                                                                   reduced_demand_df['T_int'],
                                                                   reduced_demand_df['m_ve_inf'], w_RA_gperkg)
        output_building['Q_gain_total_inf_kWh'] = reduced_demand_df['Q_gain_total_kWh'] + Q_sen_gain_inf_kWh
        ## humidity gain
        output_building['w_gain_occ_kgpers'] = reduced_demand_df['w_int']
        # output_building['w_gain_infil_kgpers'] = reduced_demand_df['m_ve_inf'] * reduced_demand_df['w_ext'] / 1000
        output_building['w_gain_infil_kgpers'] = reduced_demand_df['m_ve_inf'] * reduced_demand_df['x_ve_inf']
        # hot water demand
        output_building['Q_dhw_kWh'] = reduced_demand_df['Qww_sys']/1000
        output_building['Tww_sup_C'] = reduced_demand_df['Tww_sys_sup']
        output_building['Tww_ret_C'] = reduced_demand_df['T_ext']   # to avoid heating from ambient air
        output_building = output_building.round(4)  # osmose does not read more decimals (observation)
        # output_building = output_building.drop(output_df.index[range(7)])
        # PV potential
        if 'RET' in case:
            output_building['rad_Whperm2'] = reduced_PV_df['Wh_m2']*0.8 ## SDC case
        else:
            output_building['rad_Whperm2'] = reduced_PV_df['Wh_m2']
        # electricity consumption
        output_building['E_sys_kWh'] = reduced_demand_df['E_sys']/1000

        ## output to hcs_out
        # change units
        output_hcs['T_ext'] = reduced_demand_df['T_ext']
        output_hcs['T_ext_wb'] = reduced_demand_df['T_ext_wetbulb']
        output_hcs['COND_TIN'] = reduced_demand_df['T_ext_wetbulb'] + 5 + 273.15  # FIXME: hard-coded
        output_hcs['COND_TOUT'] = reduced_demand_df['T_ext_wetbulb'] + 4.5 + 273.15
        output_hcs['T_RA'] = reduced_demand_df['T_int']
        output_hcs['w_RA_gperkg'] = w_RA_gperkg
        output_hcs['rh_ext'] = np.where((reduced_demand_df['rh_ext'] / 100) >= 1, 0.99, reduced_demand_df['rh_ext'] / 100)
        output_hcs['w_ext'] = np.vectorize(calc_w_from_rh)(reduced_demand_df['rh_ext'],
                                                           reduced_demand_df['T_ext'])  # g/kg d.a. # TODO: check if it's the same as x_ve_inf
        ## building size
        output_hcs.loc[:, 'Af_m2'] = total_demand_df['Af_m2'][building]
        output_hcs.loc[:, 'Vf_m3'] = floor_height_m * total_demand_df['Af_m2'][building] # TODO: extract from bpr

        ## CO2 limit and minimum air flow
        reduced_demand_df = calc_CO2_gains(output_hcs, reduced_demand_df)
        output_hcs['V_CO2_max_m3'] = reduced_demand_df['V_CO2_max_m3']
        output_hcs['V_CO2_min_m3'] = reduced_demand_df['V_CO2_min_m3']
        output_hcs['v_CO2_in_infil_occupant_m3pers'] = reduced_demand_df['v_CO2_infil_window_m3pers'] + reduced_demand_df[
            'v_CO2_occupant_m3pers']
        output_hcs['CO2_ext_ppm'] = CO2_env_ppm  # TODO: get actual profile
        output_hcs['CO2_max_ppm'] = CO2_room_max_ppm
        output_hcs['m_ve_req'] = reduced_demand_df['m_ve_required']
        output_hcs['rho_air'] = np.vectorize(calc_rho_air)(reduced_demand_df['T_ext'])
        reduced_demand_df['rho_air_int'] = np.vectorize(calc_moist_air_density)(reduced_demand_df['T_int'] + 273.15,
                                                                             reduced_demand_df['x_int'])
        output_hcs['M_dry_air'] = np.vectorize(calc_m_dry_air)(output_hcs['Vf_m3'], reduced_demand_df['rho_air_int'],
                                                               reduced_demand_df['x_int'])
        output_hcs['CO2_ve_min_ppm'] = CO2_ve_min_ppm
        output_hcs['m_ve_in_calc'] = np.vectorize(
            calc_m_exhaust_from_CO2)(output_hcs['CO2_ve_min_ppm'], output_hcs['CO2_ext_ppm'],
                                     output_hcs['v_CO2_in_infil_occupant_m3pers'], output_hcs['rho_air'])
        output_hcs['m_ve_min'] = np.where(
            (output_hcs['T_ext'] <= output_hcs['T_RA']) & (output_building['Q_gain_occ_kWh'] <= 0.0), 0, output_hcs['m_ve_in_calc'])
        output_hcs['m_ve_max'] = output_hcs['m_ve_min'] * N_m_ve_max
        output_hcs['m_ve_inf'] = reduced_demand_df['m_ve_inf']

        ## humidity conditions
        output_hcs['rh_max'] = RH_max
        output_hcs['rh_min'] = RH_min
        output_hcs['w_max'] = np.vectorize(calc_w_from_rh)(output_hcs['rh_max'], reduced_demand_df['T_int'])
        output_hcs['w_min'] = np.vectorize(calc_w_from_rh)(output_hcs['rh_min'], reduced_demand_df['T_int'])
        output_hcs['m_w_max'] = np.vectorize(calc_m_w_in_air)(reduced_demand_df['T_int'], output_hcs['w_max'],
                                                              output_hcs['Vf_m3'])
        output_hcs['m_w_min'] = (np.vectorize(calc_m_w_in_air)(reduced_demand_df['T_int'], output_hcs['w_min'],
                                                               output_hcs['Vf_m3'])).min()

        output_hcs = output_hcs.round(4)  # osmose does not read more decimals (observation)
        # output_hcs = output_hcs.drop(output_df.index[range(7)])

        # get Tamb/Twb
        Tamb_K = reduced_demand_df['T_ext'].mean() + 273.15
        print 'ambient average: ', Tamb_K
        Twb_K = output_hcs['T_ext_wb'].mean() + 273.15
        print 'wetbulb average: ', Twb_K

        ## WRITE OUTPUTS
        if problem_type == 'building':
            # output a set of off coil temperatures for oau
            output_hcs = generate_oau_temperature_sets(building, output_hcs, reduced_demand_df)
            output_building.T.to_csv(path_to_osmose_project_bui(building), header=False)
            output_hcs.T.to_csv(path_to_osmose_project_hcs(building, 'hcs'), header=False)
        else:
            return output_building, output_hcs, int(timesteps), Tamb_K

        # output_df.loc[:, 'Mf_air_kg'] = output_df['Vf_m3']*calc_rho_air(24)

        # add hour of the interval
        # output_df['hour'] = range(1, 1 + timesteps)
        # TODO: delete the first few hours without demand (howwwwww?)
        # output_df = output_df.round(4)  # osmose does not read more decimals (observation)
        # output_df = output_df.reset_index()
        # output_df = output_df.drop(['index'], axis=1)
        # output_df = output_df.drop(output_df.index[range(7)])

    return building_names, Tamb_K, int(timesteps), int(periods)


def generate_oau_temperature_sets(building, output_hcs, reduced_demand_df):
    T_OAU_offcoil = np.arange(T_low_C, T_high_C, T_interval)
    output_hcs_dict = {}
    output_hcs_copy = output_hcs.copy()
    T_coil = 16
    dT_coil = 0.2
    T_iehx = 16
    dT_iehx = 0.15
    T_ER0 = 16
    dT_ER0 = 0.2
    for i in range(T_OAU_offcoil.size):
        # output hcs
        output_hcs['T_OAU_offcoil' + str(i + 1)] = T_OAU_offcoil[i]
        # output hcs_in
        output_hcs_dict[i] = output_hcs_copy
        output_hcs_dict[i]['T_OAU_offcoil'] = T_OAU_offcoil[i]
        file_name_extension = 'hcs_in' + str(i + 1)
        output_hcs_dict[i].T.to_csv(path_to_osmose_project_hcs(building, file_name_extension), header=False)
        # output input_T1
        input_T_df = pd.DataFrame()
        input_T_df['OAU_T_SA'] = output_hcs_dict[i]['T_OAU_offcoil']
        input_T_df['T_ext_C'] = reduced_demand_df['T_ext']
        input_T_df['T_dew_coil'] = T_coil  # 8 + 10
        T_coil = T_coil + dT_coil
        input_T_df['T_dew_iehx'] = T_iehx  #
        T_iehx = T_iehx + dT_iehx
        input_T_df['T_dew_er0'] = T_ER0
        T_ER0 = T_ER0 + dT_ER0
        input_T_df['COND_TIN'] = output_hcs['COND_TIN']
        input_T_df['COND_TOUT'] = output_hcs['COND_TOUT']
        input_T_df.T.to_csv(path_to_osmose_project_inputT(str(i + 1)), header=False)
    # output input_T0
    input_T0_df = pd.DataFrame()
    input_T0_df['T_ext_C'] = reduced_demand_df['T_ext']
    input_T0_df['OAU_T_SA'] = 12.6
    input_T0_df.T.to_csv(path_to_osmose_project_inputT(str(0)), header=False)
    return output_hcs


def get_humidity_ratio_assumptions(case):
    if ('OFF' in case) or ('RET' in case) or ('HOT' in case):
        w_RA_gperkg = 10.29  # 24C with 55% RH #FIXME: hard-coded
    elif 'RES' in case:
        w_RA_gperkg = 13.1  # 28C with 55% RH
    return w_RA_gperkg


def get_reduced_demand_df(case, building, end_t, start_t):
    # read demand output
    # demand_df = pd.read_csv(path_to_demand_output(building)['csv'], usecols=(BUILDINGS_DEMANDS_COLUMNS))
    building_demand_df = pd.read_excel(path_to_demand_output(building, case)['xls'])

    if type(start_t) is int:
        reduced_demand_df = building_demand_df[start_t:end_t]
        reduced_demand_df = reduced_demand_df.reset_index()
    elif (type(start_t) is dict) or (type(start_t) is OrderedDict):
        list_of_df = []
        for interval in start_t.keys():
            reduced_demand_df = building_demand_df[start_t[interval]:end_t[interval]]
            # reduced_demand_df = reduced_demand_df.reset_index()
            list_of_df.append(reduced_demand_df)
            print ('interval', interval, ', hour:', start_t[interval])
        reduced_demand_df = pd.concat(list_of_df, ignore_index=True)
        reduced_demand_df = reduced_demand_df.reset_index()
    else:
        raise ValueError('WRONG start_t: ', start_t)
    return reduced_demand_df


def get_reduced_PV_df(case, building, end_t, start_t):
    all_year_PV_per_m2_df = pd.read_csv(path_to_rad_df(case))
    if type(start_t) is int:
        PV_per_m2_df = all_year_PV_per_m2_df[start_t:end_t]
        PV_per_m2_df = PV_per_m2_df.reset_index()
    elif (type(start_t) is dict) or (type(start_t) is OrderedDict):
        list_of_df = []
        for interval in start_t.keys():
            PV_per_m2_df = all_year_PV_per_m2_df[start_t[interval]:end_t[interval]]
            list_of_df.append(PV_per_m2_df)
            print 'interval', interval, ', hour:', start_t[interval]
        PV_per_m2_df = pd.concat(list_of_df, ignore_index=True)
        PV_per_m2_df = PV_per_m2_df.reset_index()
    else:
        raise ValueError('WRONG start_t: ', start_t)
    return PV_per_m2_df



def get_timesteps_info(case, season, timesteps):
    if type(timesteps) is int:
        # one fixed period (24 or 168 timesteps)
        start_t = get_start_t(case, timesteps, season) # sharing the same start for 48
        end_t = (start_t + timesteps)
        op_time = np.ones(timesteps, dtype=int)
        periods = 1
    elif type(timesteps) is list:
        # one specific time-step
        start_t = timesteps[0]
        end_t = start_t + 1
        timesteps = 1
        op_time = np.ones(timesteps, dtype=int)
        periods = 1
    elif timesteps == 'typical days':
        # cluster_numbers_df = pd.read_excel(path_to_number_of_k_file(settings.typical_day_path), sheet_name='number_of_clusters')
        # number_of_clusters = cluster_numbers_df[case.split('_')[4]][case.split('_')[0]]
        number_of_clusters = settings.number_of_typical_days
        print('number of clusters: ', number_of_clusters)
        day_count_df = pd.read_csv(path_to_cluster_files(settings.typical_days_path, '', 'day_count', number_of_clusters))
        # typical_day_profiles = pd.read_csv(path_to_cluster_files(settings.typical_days_path, '', 'profiles', number_of_clusters))
        number_of_typical_days = day_count_df.shape[0]
        start_t, end_t = OrderedDict(), OrderedDict()
        op_time = []
        for d in range(number_of_typical_days):
            day = day_count_df['day'][d]
            start_t[int(day)] = (int(day) - 1) * 24
            end_t[int(day)] = start_t[int(day)] + 24
            count = day_count_df['count'][d]
            op_time.extend(np.ones(24, dtype=int) * count)
        # for d in range(number_of_typical_days):
        #     day = day_count_df['day'][d]
        #     T_day = typical_day_profiles['typ_1'][d * 24:(d + 1) * 24]
        #     T_md = (T_day.max() + T_day.min()) / 2  # ASHRAE method
        #     if T_md > settings.T_b_CDD:  # filter out CDD
        #         print 'day', day, 'T_md', T_md
        #         start_t[int(day)] = (int(day) - 1) * 24
        #         end_t[int(day)] = start_t[int(day)] + 24
        #         count = day_count_df['count'][d]
        #         op_time.extend(np.ones(24, dtype=int) * count)
        # periods = len(op_time) / 24
        periods = 1
        timesteps = len(op_time)
    elif timesteps == 'typical hours':
        number_of_clusters = settings.number_of_typical_hours
        print('number of typical hours: ', number_of_clusters)
        hour_count_df = pd.read_csv(path_to_cluster_files(settings.typical_hours_path, '', 'hour_count', number_of_clusters))
        start_t, end_t = OrderedDict(), OrderedDict()
        op_time = []
        for d in range(number_of_clusters):
            hour = hour_count_df['hour'][d]
            start_t[int(hour)] = hour_count_df['hour'][d] - 1
            end_t[int(hour)] = hour_count_df['hour'][d]
            op_time.extend([hour_count_df['count'][d]])
        periods = 1
        timesteps = len(op_time)
    elif timesteps == 'dtw hours':
        cluster_numbers_df = pd.read_excel(os.path.join(settings.typical_days_path, 'B005_HOT_DTW.xlsx'), header=None) # TODO: remove hard-coded value
        start_t, end_t = {}, {}
        op_time = []
        number_of_clusters = cluster_numbers_df.shape[0]
        for n_hour in range(number_of_clusters):
            start_t[n_hour] = cluster_numbers_df[0][n_hour]
            end_t[n_hour] = cluster_numbers_df[0][n_hour] + 1
            count = cluster_numbers_df[1][n_hour]
            op_time.extend(np.ones(1, dtype=int) * count)
        periods = number_of_clusters
        timesteps = number_of_clusters

    return start_t, end_t, op_time, periods, timesteps


def output_operatingcost_to_osmose(op_time, timesteps):
    operating_cost_df = pd.DataFrame()
    operating_cost_df['op_time'] = op_time
    operating_cost_df['cost_elec_in'] = np.ones(timesteps, dtype=int)
    operating_cost_df['cost_elec_out'] = np.ones(timesteps, dtype=int)
    operating_costT_df = operating_cost_df.T
    data = operating_costT_df.to_csv(None, header=False)
    open(path_to_osmose_project_op(), 'w').write(data[:-1])
    # operating_costT_df.to_csv(path_to_osmose_project_op(), header=False) # FIXME: remove the last line
    return


def calc_Q_sen_gain_inf_kWh(T_ext, T_int, m_ve_inf_kgpers, w_RA_gperkg):
    T = T_ext if T_ext <= T_int else T_int #FIXME: double check if this is true, should be T_ext
    h_sen_inf_kJperkg = calc_h_from_T_w(T, w_RA_gperkg)
    Q_gain_inf_kWh = m_ve_inf_kgpers * h_sen_inf_kJperkg
    return Q_gain_inf_kWh


def calc_CO2_gains(output_hcs, reduced_tsd_df):
    reduced_tsd_df['CO2_ext_ppm'] = CO2_env_ppm  # m3 CO2/m3
    # from occupants
    reduced_tsd_df['v_CO2_occupant_m3pers'] = calc_co2_from_occupants(reduced_tsd_df['people'])
    # from inlet air
    reduced_tsd_df['rho_air'] = np.vectorize(calc_rho_air)(reduced_tsd_df['T_ext'])  # kg/m3
    reduced_tsd_df['v_in_infil_window'] = (reduced_tsd_df['m_ve_inf'] + reduced_tsd_df['m_ve_window']) / \
                                          reduced_tsd_df['rho_air']
    reduced_tsd_df['v_CO2_infil_window_m3pers'] = reduced_tsd_df['v_in_infil_window'] * reduced_tsd_df['CO2_ext_ppm']
    reduced_tsd_df['V_CO2_max_m3'] = output_hcs['Vf_m3'] * CO2_room_max_ppm
    reduced_tsd_df['V_CO2_min_m3'] = output_hcs['Vf_m3'] * CO2_room_min_ppm
    return reduced_tsd_df


def calc_sensible_gains(reduced_tsd_df):
    # radiation
    reduced_tsd_df['Q_gain_rad_kWh'] = reduced_tsd_df['I_sol_and_I_rad'] / 1000
    # environment
    reduced_tsd_df['Q_gain_env_kWh'] = reduced_tsd_df.loc[:, Q_GAIN_ENV].sum(axis=1) / 1000
    # internal (appliances, lighting...)
    reduced_tsd_df['Q_gain_int_kWh'] = reduced_tsd_df.loc[:, Q_GAIN_INT].sum(axis=1) / 1000
    # occupant
    reduced_tsd_df['Q_gain_occ_kWh'] = reduced_tsd_df['Q_gain_sen_peop'] / 1000
    # total
    reduced_tsd_df['Q_gain_total_kWh'] = reduced_tsd_df['Q_gain_rad_kWh'] + reduced_tsd_df['Q_gain_env_kWh'] + \
                                         reduced_tsd_df[
                                             'Q_gain_int_kWh'] + reduced_tsd_df['Q_gain_occ_kWh']
    return reduced_tsd_df


def calc_m_w_in_air(Troom_C, w_gperkg, Vf_m3):
    Troom_K = Troom_C + 273.15
    w_kgperkg = w_gperkg / 1000
    rho_ma_kgperm3 = calc_moist_air_density(Troom_K, w_kgperkg)
    m_dry_air_kg = calc_m_dry_air(Vf_m3, rho_ma_kgperm3, w_kgperkg)
    m_w_kgpers = m_dry_air_kg * w_kgperkg / 3600
    return m_w_kgpers


def calc_m_dry_air(Vf_m3, rho_ma_kgperm3, w_kgperkg):
    m_moist_air_kg = Vf_m3 * rho_ma_kgperm3
    m_dry_air_kg = m_moist_air_kg / (1 + w_kgperkg)
    return m_dry_air_kg


def calc_moist_air_density(Troom_K, w_kgperkg):
    term1 = (Pair_Pa / (Ra_JperkgK * Troom_K)) * (1 + w_kgperkg)
    term2 = (1 + w_kgperkg * Rw_JperkgK / Ra_JperkgK)
    rho_ma_kgperm3 = term1 / term2
    return rho_ma_kgperm3


def calc_co2_from_occupants(occupants):
    # from Jeremie's thesis
    v_CO2_m3pers = v_CO2_Lpers / 1000
    v_CO2_m3pers = v_CO2_m3pers * occupants
    return v_CO2_m3pers


def calc_w_from_rh(rh, t):
    rh = rh / 100
    pws = p_ws_from_t(t)
    pw = p_w_from_rh_p_and_ws(rh, pws)
    p = 101325  # [Pa]
    w = hum_ratio_from_p_w_and_p(pw, p)
    return w * 1000  # g/kg d.a.


def calc_m_exhaust_from_CO2(CO2_room, CO2_ext, CO2_gain_m3pers, rho_air):
    # assuming m_exhaust = m_ve_mech - m_ve_inf
    m_exhaust_kgpers = CO2_gain_m3pers * rho_air / (CO2_room - CO2_ext)
    return m_exhaust_kgpers

def get_start_t(case, timesteps, season):
    """
    WTP: 5/16: 3240, Average Annual 7/30-8/5: 5040-5207
    ABU: 7/6 - 7/12: 4464
    HKG: 7/15 - 7/21: 4680, Friday - Thursday
    :param case:
    :return:
    """
    START_t_168_dict = {'ABU': {'Summer': 4464, 'Winter': 456, 'Autumn': 7008, 'Spring': 2424},
                        'WTP': {'Summer': 5064},
                        'HKG': {'Summer': 4680, 'Winter': 168, 'Autumn': 7728, 'Spring': 2328},
                        'MDL': {'Wet': 5016, 'Dry': 8016}}

    START_t_24_dict = {'ABU': {'Summer': 4512, 'Winter': 456, 'Autumn': 7008, 'Spring': 2424},
                       'WTP': {'Summer': 5136},
                       'HKG': {'Summer': 4680, 'Winter': 168, 'Autumn': 7728, 'Spring': 2328},
                       'MDL': {'Wet': 5016, 'Dry': 8016}}
    if timesteps == 168 or 48:
        for key in START_t_168_dict.keys():
            if key in case:
                start_t = START_t_168_dict[key][season]
    else:
        for key in START_t_24_dict.keys():
            if key in case:
                start_t = START_t_24_dict[key][season]

    return start_t


def get_RH_limits_assumptions(case):
    RH_max_dict = {'WTP': 80, 'ABU': 70, 'HKG': 80, 'MDL': 80}
    RH_min_dict = {'WTP': 40, 'ABU': 30, 'HKG': 40, 'MDL': 40}
    for key in RH_max_dict.keys():
        if key in case:
            RH_max = RH_max_dict[key]
            RH_min = RH_min_dict[key]

    return RH_max, RH_min

##  Paths (TODO: connected with cea.config and inputLocator)
def path_to_demand_output(building_name, case):
    path_to_file = {}
    path_to_folder = 'C:\\CEA_cases\\HCS_cases_all\\%s\\outputs\\data\\demand' % case
    path_to_file['csv'] = os.path.join(path_to_folder, '%s.%s' % (building_name, 'csv'))
    path_to_file['xls'] = os.path.join(path_to_folder, '%s.%s' % (building_name, 'xls'))
    return path_to_file

def path_to_total_demand(case):
    path_to_folder = 'C:\\CEA_cases\\HCS_cases_all\\%s\\outputs\\data\\demand' % case
    path_to_file = os.path.join(path_to_folder, 'Total_demand.%s' % ('csv'))
    return path_to_file

def path_to_district_df(case):
    path_to_folder = 'C:\\CEA_cases\\HCS_cases_all\\%s\\outputs\\data\\demand' % case
    path_to_file = os.path.join(path_to_folder, 'Total_demand.%s' % ('csv'))
    return path_to_file

def path_to_PV_df(case):
    path_to_folder = 'C:\\CEA_cases\\HCS_cases_all\\%s\\outputs\\data' % case
    path_to_file = os.path.join(path_to_folder, 'PV_Wh_per_m2.%s' % ('csv'))
    return path_to_file

def path_to_rad_df(case):
    path_to_folder = 'C:\\CEA_cases\\HCS_cases_all\\%s\\outputs\\data' % case
    path_to_file = os.path.join(path_to_folder, 'rad_Whm2.%s' % ('csv'))
    return path_to_file

def path_to_osmose_project_bui(building_name):
    format = 'csv'
    path_to_folder = settings.osmose_project_data_path
    path_to_file = os.path.join(path_to_folder, '%s_from_cea.%s' % (building_name, format))
    print('saved ', path_to_file)
    return path_to_file

def path_to_osmose_project_hcs(building_name, extension):
    format = 'csv'
    path_to_folder = settings.osmose_project_data_path
    path_to_file = os.path.join(path_to_folder, '%s_from_cea_%s.%s' % (building_name, extension, format))
    return path_to_file

def path_to_osmose_project_inputT(number):
    format = 'csv'
    path_to_folder = settings.osmose_project_data_path
    path_to_file = os.path.join(path_to_folder, 'input_T%s.%s' % (number, format))
    return path_to_file

def path_to_cluster_files(path, case, name, cluster_numbers):
    format = 'csv'
    path_to_folder = os.path.join(path, case)
    path_to_folder = os.path.join(path_to_folder, 'k_'+str(cluster_numbers))
    path_to_file = os.path.join(path_to_folder, '%s.%s' % (name, format))
    return path_to_file

def path_to_number_of_k_file(path):
    format = 'xlsx'
    path_to_file = os.path.join(path, 'number_of_k.%s' % (format))
    return path_to_file

def path_to_osmose_project_op():
    format = 'csv'
    path_to_folder = settings.osmose_project_data_path
    path_to_file = os.path.join(path_to_folder, 'operatingcost.%s' % (format))
    return path_to_file




if __name__ == '__main__':
    case = 'WTP_CBD_m_WP1_OFF'
    # timesteps = 168  # 168 (week)
    timesteps = settings.timesteps
    specified_buildings = ["B005"]
    season = 'Summer'
    extract_cea_outputs_to_osmose_main(case, timesteps, season, specified_buildings)
