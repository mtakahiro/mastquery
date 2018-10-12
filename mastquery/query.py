"""
Demo of querying the ESA HST archive
"""

import json

import numpy as np

MASTER_COLORS = {'G102':'#1f77b4',
'F125W':'#ff7f0e',
'F160W':'#2ca02c',
'G141':'#d62728',
'F140W':'#9467bd',
'F105W':'#8c564b',
'F775W':'#8c564b'}

# DEFAULT_RENAME = {'OPTICAL_ELEMENT_NAME':'FILTER',
#                   'EXPOSURE_DURATION':'EXPTIME',
#                   #'INSTRUMENT_NAME':'INSTRUMENT', 
#                   #'DETECTOR_NAME':'DETECTOR', 
#                   'STC_S':'FOOTPRINT', 
#                   #'SPATIAL_RESOLUTION':'PIXSCALE', 
#                   'TARGET_NAME':'TARGET', 
#                   'SET_ID':'VISIT'}

# Wide-field instruments
ALL_INSTRUMENTS = ['WFC3/IR','WFC3/UVIS','ACS/HRC','ACS/WFC','WFPC2/PC','WFPC2/WFC']

DEFAULT_RENAME = {'t_exptime':'exptime',
                  'target_name':'target',
                  's_region':'footprint', 
                  's_ra':'ra',
                  's_dec':'dec',
                  'filters':'filter'}
                  
DEFAULT_COLUMN_FORMAT = {'t_min':'.4f',
           't_max':'.4f',
           'exptime':'.0f',
           'ra':'.6f',
           'dec':'.6f'}

# Don't get calibrations.  Can't use "INTENT LIKE 'SCIENCE'" because some 
# science observations are flagged as 'Calibration' in the ESA HSA.
#DEFAULT_QUERY = {'project':['HST'], 'intentType':['science'], 'mtFlag':['False']}
DEFAULT_QUERY = {'obs_collection':['HST'], 'intentType':['science'], 'mtFlag':['False']}

# DEFAULT_EXTRA += ["TARGET.TARGET_NAME NOT LIKE '{0}'".format(calib) 
#                  for calib in ['DARK','EARTH-CALIB', 'TUNGSTEN', 'BIAS',
#                                'DARK-EARTH-CALIB', 'DARK-NM', 'DEUTERIUM',
#                                'INTFLAT', 'KSPOTS', 'VISFLAT']]

INSTRUMENT_DETECTORS = {'WFC3/UVIS':'UVIS', 'WFC3/IR':'IR', 'ACS/WFC':'WFC', 'ACS/HRC':'HRC', 'WFPC2':'1', 'STIS/NUV':'NUV-MAMA', 'STIS/ACQ':'CCD'}

def get_correct_exposure_times(tab, in_place=True, ni=200):
    # Split into smaller groups
    #ni = 200
    N = len(tab) // ni
    exptime = [_get_correct_exposure_times(tab[i*ni:(i+1)*ni], in_place=False) for i in range(N+(len(tab)/ni != N))]
    
    if in_place:
        tab['exptime'] = np.hstack(exptime)
        tab['exptime'].format = '.1f'
    else:
        return np.hstack(exptime)
            
def _get_correct_exposure_times(tab, in_place=True):
    """
    Query direct from mast
    """
    import os
    import time
    from astropy.table import Table
    
    url = "http://archive.stsci.edu/hst/search.php?action=Search&sci_data_set_name={datasets}&max_records=1000&outputformat=CSV"
    dataset_list = [o[-18:-9] for o in tab['dataURL']]
    datasets = ','.join(dataset_list)

    query_url = url.format(datasets=datasets)
    #os.system('curl -o mast.csv '+query_url)
    try:
        mast = Table.read(query_url, format='csv')[1:]
        #time.sleep(5)    
    except:
        print('get_correct_exptime: read failed')
        #tab['exptime'] = -1.
        #tab['exptime'].format = '.1f'
        if in_place:
            return False
        else:
            return np.zeros(len(tab))-1
    
    if len(tab) == len(mast):
        som = [list(mast['Dataset']).index(o.upper()) for o in dataset_list]
        tab['mexptime'] = 1.
        mast_time = np.array([float(t) for t in mast['Exp Time']])
        if in_place:
            tab['exptime']= mast_time[som]
            tab['exptime'].format = '.1f'
        else:
            return mast_time[som]
    else:
        print('get_correct_exptime: tables don\'t match ({0} {1})'.format(len(tab), len(mast)))
        #tab['exptime'] = -1.
        #tab['exptime'].format = '.1f'
        if in_place:
            return False
        else:
            return np.zeros(len(tab))-1
        
        
def get_products_table(query_tab, extensions=['RAW']):
    """
    Get a new table with the association products
    """
    from astropy import table
    from . import utils
    
    obsid=','.join(['{0}'.format(o) for o in query_tab['obsid']])
    
    request = {'service':'Mast.Caom.Products',
       'params':{'obsid':obsid},
       'format':'json',
       'pagesize':10000,
       'page':1}   

    headers, outString = utils.mastQuery(request)
    outData = json.loads(outString)
    prod_tab = utils.mastJson2Table(outData)
    prod_tab.rename_column('parent_obsid', 'obsid')
    prod_tab.remove_column('proposal_id')
    prod_tab.rename_column('obs_id', 'observation_id')
    
    col = 'productSubGroupDescription'
    ext = np.vstack([prod_tab[col] == e for e in extensions]).sum(axis=0) > 0
    
    full_tab = table.join(prod_tab[ext], query_tab, 
                          keys='obsid', join_type='inner')
    
    full_tab.sort(['observation_id'])
    
    return full_tab

DEFAULT_QUERY_ASTROQUERY = {'intentType': ['science'], 'mtFlag': ['False'], 'obs_collection': ['HST']}

def run_query(box=None, get_exptime=True, rename_columns=DEFAULT_RENAME,
              sort_column=['obs_id', 'filter'],
              base_query=DEFAULT_QUERY_ASTROQUERY, **kwargs):
    """
    Run MAST query with astroquery.mast.  
    
    All columns listed at https://mast.stsci.edu/api/v0/_c_a_o_mfields.html 
    can be used for the query.
    """                  
    import time
    from astroquery.mast import Observations
    from astropy.coordinates import SkyCoord
    import astropy.units as u
           
    query_args = {}
    for k in base_query:
        query_args[k] = base_query[k]
    
    for k in kwargs:
        if k == 'instruments':
            query_args['instrument_name'] = kwargs[k]
        elif k == 'proposal_id':
            query_args['proposal_id'] = ['{0}'.format(p) for p in kwargs[k]]
        elif k == 'extensions':
            continue
        else:
            query_args[k] = kwargs[k]
            
    if (box is not None):
        ra, dec, radius = box
        coo = SkyCoord(ra*u.deg, dec*u.deg)        
        query_args['coordinates'] = coo
        query_args['radius'] = radius*u.arcmin
        
    tab = Observations.query_criteria(**query_args)                               
    
    tab.meta['qtime'] = time.ctime(), 'Query timestamp'
    
    if len(tab) == 0:
        return tab
    
    tab = modify_table(tab, get_exptime=get_exptime, 
                       rename_columns=rename_columns,
                       sort_column=sort_column)
    return tab
    
def run_query_old(box=None, proposal_id=[13871], instruments=['WFC3/IR'], filters=[], extensions=['RAW','C1M'], base_query=DEFAULT_QUERY, maxitems=100000, timeout=300, rename_columns=DEFAULT_RENAME, lower=True, sort_column=['obs_id', 'filter'], remove_tempfile=True, get_query_string=False, quiet=True, coordinate_transforms=True, get_exptime=True):
    """
    
    Optional position box query:
        box = [ra, dec, radius] with ra and dec in decimal degrees and radius
        in arcminutes.
    
    Some science observations are flagged as INTENT = Calibration, so may have
    to run with extra=[] for those cases and strip out true calibs another
    way.
    
    """
    import os
    import tempfile   
    import urllib.request
    import time
    
    from astropy.table import Table
    from . import utils
    
    if quiet:
        utils.set_warnings(numpy_level='ignore', astropy_level='ignore')
        
    request = {'params':{"columns":"*"},
               'format':'json',
               'pagesize':maxitems,
               'page':1,
               'removenullcolumns':True,
               'timeout':timeout,
               'removecache':True}

    # Box search around position
    if (box is not None):
        ra, dec, radius = box
        box_str = "{0}, {1}, {2}".format(ra, dec, radius/60.)
        request['params']['position'] = box_str
        request['service'] = 'Mast.Caom.Filtered.Position'
    else:
        request['service'] = 'Mast.Caom.Filtered'

    query = {}
    for k in base_query:
        query[k] = base_query[k]

    if len(proposal_id) > 0:
        query['proposal_id'] = ['{0}'.format(p) for p in proposal_id]
        
    if len(filters) > 0:
        query['filters'] = filters

    if len(instruments) > 0:
        query['instrument_name'] = instruments
    
    # Translate to filter format
    query_list = []
    for k in query:
        # Range
        if k.startswith('!'):
            query_list.append({"paramName":k[1:], 'values':[{'min':query[k][0], 'max':query[k][1]}]})
        elif k.startswith('*'):
            query_list.append({"paramName":k[1:], 'values':[], 'freeText':query[k]})
        else:
            query_list.append({"paramName":k, 'values':query[k]})
            
    request['params']['filters'] = query_list
            
    if get_query_string:
        return request
    
    # Run the query
    headers, outString = utils.mastQuery(request)

    outData = json.loads(outString)
    tab = utils.mastJson2Table(outData)

    try:
        outData = json.loads(outString)
        tab = utils.mastJson2Table(outData)
    except:
        print('Failed to initialize the table (result={0})'.format(outString))
        return False
        
    tab.meta['query'] = json.dumps(request), 'Query input'
    tab.meta['qtime'] = time.ctime(), 'Query timestamp'
    
    if len(tab) == 0:
        return tab
    
    tab = modify_table(tab, get_exptime=get_exptime, 
                       rename_columns=rename_columns,
                       sort_column=sort_column)
    return tab
    
def modify_table(tab, get_exptime=True, rename_columns=DEFAULT_RENAME, 
                 sort_column=['obs_id', 'filter']):
    
    # Add coordinate name
    if 'ra' in tab.colnames:
        jtargname = [utils.radec_to_targname(ra=tab['ra'][i], dec=tab['dec'][i], scl=6) for i in range(len(tab))]
        tab['jtargname'] = jtargname
    
    fix_byte_columns(tab)
        
    for c in rename_columns:
        if c in tab.colnames:
            tab.rename_column(c, rename_columns[c])
        
    # cols = tab.colnames
    # if ('instrument' in cols) & ('detector' in cols):
    #     tab['instdet'] = ['{0}/{1}'.format(tab['instrument'][i], tab['detector'][i]) for i in range(len(tab))]
            
    #tab['OBSERVATION_ID','orientat'][so].show_in_browser(jsviewer=True)
    
    set_default_formats(tab)
    
    # Visit ID
    tab['visit'] = [o[4:6] for o in tab['obs_id']]
    
    # Area
    #set_area_column(tab)

    # Orientat
    #set_orientat_column(tab)
    
    # Sort
    tab.sort(sort_column)
    
    # Correct exposure time
    if get_exptime:
        get_correct_exposure_times(tab)
        
    return tab

def fix_byte_columns(tab):
    for col in tab.colnames:
        try:
            if tab[col].dtype == np.dtype('O'):
                strcol = [item.decode('utf-8') for item in tab[col]]
                tab.remove_column(col)
                tab[col] = strcol
        except:
            pass
            
def add_postcard(table, resolution=256):
    
   url = ['http://archives.esac.esa.int/ehst-sl-server/servlet/data-action?OBSERVATION_ID={0}&RETRIEVAL_TYPE=POSTCARD&RESOLUTION={1}'.format(o, resolution) for o in table['observation_id']]
   
   img = ['<a href="{0}"><img src="{0}"></a>'.format(u) for u in url]
   table['postcard'] = img
   
   return True
   
   if False:
       tab = grizli.utils.GTable(table)
       tab['observation_id','filter','orientat','postcard'][tab['visit'] == 1].write_sortable_html('tab.html', replace_braces=True, localhost=True, max_lines=10000, table_id=None, table_class='display compact', css=None)
        
def parse_polygons(polystr):
    from astropy.coordinates import Angle
    import astropy.units as u
    
    if hasattr(polystr, 'decode'):
        polyspl = polystr.decode('utf-8').strip().split('POLYGON')#strip()[1:-1].split(',')
    else:
        polyspl = polystr.strip().split('POLYGON')
    
    poly = []
    for pp in polyspl:
        if not pp:
            continue
            
        spl = pp.strip().split()
        for ip, p in enumerate(spl):
            try:
                pf = float(p)
                break
            except:
                continue
    
        poly_i = np.cast[float](spl[ip:]).reshape((-1,2)) #[np.cast[float](p.split()).reshape((-1,2)) for p in spl]
    
        ra = Angle(poly_i[:,0]*u.deg).wrap_at(360*u.deg).value
        poly_i[:,0] = ra
        poly.append(poly_i)
        
    return poly
    
def set_default_formats(table, formats=DEFAULT_COLUMN_FORMAT):
    """
    Set default print formats
    """
    
    for f in formats:
        if f in table.colnames:
            table[f].format = formats[f]

def set_expstart(table):
    from astropy import time
    mjd = time.Time(table['t_min'], format='mjd')
    table['expstart'] = mjd.iso
    
def set_transformed_coordinates(table):
    """
    Set GeocentricTrueEcliptic and Galactic coordinate tranformations
    from `astropy.coordinates`.
    """
    from astropy import coordinates
    import astropy.units as u
    
    coo = coordinates.SkyCoord(ra=table['ra']*u.deg, dec=table['dec']*u.deg)
    table.rd = coo

    ecl = coo.transform_to(coordinates.GeocentricTrueEcliptic())
    table['ecl_lat'] = ecl.lat
    table['ecl_lat'].format = '.1f'

    table['ecl_lon'] = ecl.lon
    table['ecl_lon'].format = '.1f'

    gal = coo.transform_to(coordinates.Galactic())
    table['gal_l'] = gal.l
    table['gal_l'].format = '.1f'

    table['gal_b'] = gal.b
    table['gal_b'].format = '.1f'
    
def set_area_column(table):
    """
    Make a column in the `table` computing each orientation with
    `get_orientat`.
    """
    import astropy.units as u
    
    area = []
    for p in table['footprint']:
        try:
            a = get_footprint_area(p)
        except:
            a = np.nan
        area.append(a)
        
    table['area'] = area
    table['area'].format = '.1f'
    table['area'].unit = u.arcmin**2
    
def get_footprint_area(polystr='Polygon ICRS 127.465487 18.855605 127.425760 18.853486 127.423118 18.887458 127.463833 18.889591'):
    from shapely.geometry import Polygon
    
    px = parse_polygons(polystr)[0]
    poly = Polygon(px)
    cosd = np.cos(px[0,1]/180*np.pi)
    area = poly.area*3600*cosd
    return area
    
def set_orientat_column(table):
    """
    Make a column in the `table` computing each orientation with
    `get_orientat`.
    """
    table['orientat'] = [get_orientat(p) for p in table['footprint']]
    table['orientat'].format = '.1f'
    
def get_orientat(polystr='Polygon ICRS 127.465487 18.855605 127.425760 18.853486 127.423118 18.887458 127.463833 18.889591'):
    """
    
    Compute the "ORIENTAT" position angle (PA of the detector +y axis) from  
    the archive footprint, assuming that the first two entries of the polygon 
    are the LL and UL corners of the detector.
    
    """
    from astropy.coordinates import Angle
    import astropy.units as u
    
    p = parse_polygons(polystr)[0]
    
    # try:
    #     p = parse_polygons(polystr)[0]
    # except:
    #     p = old_parse_polygons(polystr)[0]
        
    dra = (p[1,0]-p[0,0])*np.cos(p[0,1]/180*np.pi)
    dde = p[1,1] - p[0,1]
    
    orientat = 90+np.arctan2(dra, dde)/np.pi*180
    orientat -= 0.24 # small offset to better match header keywords
    
    orientat = Angle.wrap_at(orientat*u.deg, 180*u.deg).value
    
    return orientat
    
def show_footprints(tab, ax=None):
    """
    Show pointing footprints in a plot
    """
    import matplotlib.pyplot as plt
    
    # Show polygons
    mpl_colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    filters = np.unique(tab['filter'])

    colors = {}
    
    if ax is None:
        ax = plt
        
    for i, f in enumerate(filters):
        if f in MASTER_COLORS:
            colors[f] = MASTER_COLORS[f]
        else:
            colors[f] = mpl_colors[i % len(mpl_colors)]
        
    for i in range(len(tab)):
        poly = parse_polygons(tab['footprint'][i])#[0]

        for p in poly:
            pclose = np.vstack([p, p[0,:]]) # repeat the first vertex to close
            
            ax.plot(pclose[:,0], pclose[:,1], alpha=0.1, color=colors[tab['filter'][i]])
            
            # Plot a point at the first vertex, pixel x=y=0.
            ax.scatter(pclose[0,0], pclose[0,1], marker='.', color=colors[tab['filter'][i]], alpha=0.1)
    
    return colors
    

