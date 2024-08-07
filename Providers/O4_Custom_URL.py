import requests
import random
import time
user_agent_generic="Mozilla/5.0 (X11; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0"
# In case of providers whose request do not follow a regular pattern, you can use code here to form it


############################################################################################################
# list of affected provider_codes
custom_url_list=('DK','DOP40','NIB','Here')
custom_url_list = custom_url_list+tuple([x + '_NAIP' for x in (
     'AL','AR','AZ','CA','CO','CT','DE','FL','GA','IA','ID','IL',
     'IN','KS','KY','LA','MA','MD','ME','MI','MN','MO','MS','MT',
     'NC','ND','NE','NH','NJ','NM','NV','NY','OH','OK','OR','PA',
     'RI','SC','SD','TN','TX','UT','VA','VT','WA','WI','WV','WY')])
############################################################################################################


############################################################################################################
# might get some session tokens here
############################################################################################################

# Denmark
DK_time=time.time()
DK_ticket=None
def get_DK_ticket():
    global DK_time, DK_ticket
    while DK_ticket=="loading":
        print("    Waiting for DK ticket to be updated.")
        time.sleep(3)
    if (not DK_ticket) or (time.time()-DK_time)>=3600:
        DK_ticket="loading"
        tmp=requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS
        requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS='HIGH:!DH:!aNULL'
        DK_ticket=requests.get("https://sdfekort.dk/spatialmap?").content.decode().split('ticket=')[1].split("'")[0]
        requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS=tmp
        DK_time=time.time()
    return DK_ticket

# Germany DOP40
DOP40_time=time.time()
DOP40_cookie=None
def get_DOP40_cookie():
    global DOP40_time, DOP40_cookie
    while DOP40_cookie=="loading":
        print("    Waiting for DOP40 cookie to be updated.")
        time.sleep(3)
    if (not DOP40_cookie) or (time.time()-DOP40_time)>=3600:
        DOP40_cookie="loading"
        DOP40_cookie=requests.Session().get('https://sg.geodatenzentrum.de/web_bkg_webmap/lib/bkgwebmap-0.12.4.all.min.js?bkg_appid=4cc455dc-a595-bbcf-0d00-c1d81caab5c3').headers['Set-Cookie'].split(';')[0]
        DOP40_time=time.time()
    return DOP40_cookie

# NorgeIbilder
NIB_time=time.time()
NIB_token=None
def get_NIB_token():
    global NIB_time, NIB_token
    while NIB_token=="loading":
        print("    Waiting for NIB token to be updated.")
        time.sleep(3)
    if (not NIB_token) or (time.time()-NIB_time)>=3600:
        NIB_token="loading"
        NIB_token=str(requests.get('https://www.norgeibilder.no').content).split('nibToken')[1].split("'")[1][:-1]
        NIB_time=time.time()
    return NIB_token
        
# Here
Here_time=time.time()
Here_value=None
def get_Here_value():
    global Here_time, Here_value
    while Here_value=="loading":
        print("    Waiting for Here value to be updated.")
        time.sleep(3)
    if (not Here_value) or (time.time()-Here_time)>=10000:
        Here_value="loading"
        js_path=str(requests.get('https://wego.here.com').content).split('<script defer="defer" src="')[1][:100].split('"')[0]
        print("js_path: "+js_path)
        Here_value=str(requests.get('https://wego.here.com'+js_path).content).split('PLATFORM_API_KEY:"')[1][:100].split('"')[0]
        print("Here_value: "+Here_value)
        Here_time=time.time()
    return Here_value

############################################################################################################

def custom_wms_request(bbox,width,height,provider):
    if provider['code']=='DK':
        (xmin,ymax,xmax,ymin)=bbox
        bbox_string=str(xmin)+','+str(ymin)+','+str(xmax)+','+str(ymax)
        url="http://kortforsyningen.kms.dk/orto_foraar?TICKET="+get_DK_ticket()+"&SERVICE=WMS&VERSION=1.1.1&FORMAT=image/jpeg&REQUEST=GetMap&LAYERS=orto_foraar&STYLES=&SRS=EPSG:3857&WIDTH="+str(width)+"&HEIGHT="+str(height)+"&BBOX="+bbox_string
        return (url,None)
    elif provider['code']=='DOP40':
        (xmin,ymax,xmax,ymin)=bbox
        bbox_string=str(xmin)+','+str(ymin)+','+str(xmax)+','+str(ymax)
        url="http://sg.geodatenzentrum.de/wms_dop40?&SERVICE=WMS&VERSION=1.1.1&FORMAT=image/jpeg&REQUEST=GetMap&LAYERS=rgb&STYLES=&SRS=EPSG:25832&WIDTH="+str(width)+"&HEIGHT="+str(height)+"&BBOX="+bbox_string
        fake_headers={'User-Agent':user_agent_generic,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Connection':'keep-alive','Accept-Encoding':'gzip, deflate','Cookie':get_DOP40_cookie(),'Referer':'http://sg.geodatenzentrum.de/web_bkg_webmap/applications/dop/dop_viewer.html'}
        return (url,fake_headers)
    elif '_NAIP' in provider['code']:
        (xmin,ymax,xmax,ymin)=bbox
        url="https://gis.apfo.usda.gov/arcgis/rest/services/NAIP_Historical/"+provider['code']+"/ImageServer/exportImage?f=image&bbox="+str(xmin)+"%2C"+str(ymin)+"%2C"+str(xmax)+"%2C"+str(ymax)+"&imageSR=102100&bboxSR=102100&size="+str(width)+"%2C"+str(height)
        return (url,None)

def custom_tms_request(tilematrix,til_x,til_y,provider):
    if provider['code']=='NIB':
        NIB_token=get_NIB_token()
        url="https://tilecache.norgeibilder.no/arcgis/rest/services/Nibcache_UTM33_EUREF89_v2/MapServer/tile/"+str(tilematrix)+"/"+str(til_y)+"/"+str(til_x)+"?token="+NIB_token
        return (url,None)
    elif provider['code']=='Here':
        Here_value=get_Here_value()
        fake_headers={'User-Agent':user_agent_generic,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8','Connection':'keep-alive','Accept-Encoding':'gzip, deflate','Referer':'https://wego.here.com/'}
        url="https://maps.hereapi.com/v3/background/mc/"+str(tilematrix)+"/"+str(til_x)+"/"+str(til_y)+"/jpeg?apikey="+Here_value+"&style=satellite.day&ppi=100&size=256"
        return (url,fake_headers)
