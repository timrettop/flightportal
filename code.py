import os, time, gc, math
import board, displayio, terminalio
import adafruit_display_text.label
import neopixel
from adafruit_matrixportal.matrixportal import MatrixPortal
from microcontroller import watchdog as w
from watchdog import WatchDogMode
import wifi, socketpool, ssl, adafruit_requests
from flightlogic import classify_flight, queue_mode, resolve_route, passes_direction_filter, parse_fr24_row

# Watchdog disabled - WatchDogMode.RESET not supported on ESP32-S3 in CP9+
#w.timeout = 60
#w.mode = WatchDogMode.RESET

def wfeed():
    try: w.feed()
    except: pass

FONT = terminalio.FONT

try:
    from secrets import secrets # type: ignore
except ImportError:
    raise

try:
    from config import config
except ImportError:
    raise

DEMO_MODE = config.get("demo_mode", False)
if DEMO_MODE:
    from demo_feed import get_flights_demo

QUERY_DELAY        = 30
BOUNDS_BOX         = config.get("bounds_box", "")
HOME_AIRPORT       = config.get("home_airport", "")
MY_LAT             = secrets.get("my_lat", 0.0000)
MY_LON             = secrets.get("my_lon", 0.0000)
FILTER_DIRECTION   = config.get("filter_direction", False)
HEADING_MIN        = config.get("heading_min", 240)
HEADING_MAX        = config.get("heading_max", 300)
MIN_ALTITUDE      = config.get("min_altitude", 0)
MAX_ALTITUDE      = config.get("max_altitude", 7000)
SHOW_ARRIVALS     = config.get("show_arrivals", True)
SHOW_DEPARTURES   = config.get("show_departures", True)
ARRIVAL_HEADING   = config.get("arrival_heading", (HEADING_MIN + HEADING_MAX) / 2)
HEADING_TOLERANCE = config.get("heading_tolerance", 50)
TEMP_UNIT          = config.get("temp_unit", "F")
MY_TIMEZONE        = config.get("timezone", "UTC")
SHOW_FULL_AIRCRAFT = config.get("show_full_aircraft", False)
SHOW_HELICOPTERS   = config.get("show_helicopters", False)

# Feature flags
ENABLE_FLIGHTS  = config.get("enable_flights",  True)
ENABLE_WEATHER  = config.get("enable_weather",  True)

# Colours
ROW_ONE_COLOUR   = 0xFFFFFF
ROW_TWO_COLOUR   = 0xFFFFFF
ROW_THREE_COLOUR = 0xFFFFFF
PLANE_COLOUR     = 0x4B0082
TEXT_SPEED       = 0.04
FLAP_SPEED       = 0.03
FLAP_CHARS       = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.'

# URLs
FLIGHT_URL  = "https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds=" + BOUNDS_BOX + "&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=0&maxage=14400&gliders=0&stats=0&ems=1&limit=60"
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude="+str(MY_LAT)
    +"&longitude="+str(MY_LON)
    +"&current_weather=true"
    +"&daily=sunrise,sunset"
    +"&timezone="+MY_TIMEZONE.replace("/", "%2F")
    +"&forecast_days=1"
    +("&temperature_unit=fahrenheit" if TEMP_UNIT == "F" else "")
)

HEXDB_URL = "https://hexdb.io/api/v1/aircraft/"
ADSB_URL  = "https://api.adsb.lol/v2/hex/"

rheaders = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
    "cache-control": "no-store, no-cache, must-revalidate, post-check=0, pre-check=0",
    "Accept": "application/json"
}



# ---- WiFi ----
def connect_wifi():
    ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    pwd  = os.getenv("CIRCUITPY_WIFI_PASSWORD")
    for attempt in range(5):
        try:
            print("WiFi connect attempt "+str(attempt+1)+"...")
            wfeed()
            wifi.radio.connect(ssid, pwd)
            print("Connected to "+ssid)
            return True
        except Exception as e:
            print("WiFi failed: "+str(e))
            wfeed()
            time.sleep(3)
    return False

def checkConnection():
    if wifi.radio.ipv4_address:
        return True
    return connect_wifi()

connect_wifi()

def setup_requests():
    pool = socketpool.SocketPool(wifi.radio)
    return adafruit_requests.Session(pool, ssl.create_default_context())

requests_session = setup_requests()



# ---- Lookups ----
GA_TYPES = {'C172','C182','C208','PC12','TBM9','SR22','SR20','DA40','DA42',
            'PA28','PA46','E55P','C525','C550','C56X','C680','C750','GL5T','GLEX'}
GA_COLOUR         = 0x00FF00
COMMERCIAL_COLOUR = 0xEE82EE

AIRLINE_INFO = {
    'SWR':('Swiss Air',0xFF0000),'OAW':('Swiss Air',0xFF0000),
    'DLH':('Lufthansa',0xFFCC00),'BAW':('British Airw',0x003399),
    'EZY':('easyJet',0xFF6600),'RYR':('Ryanair',0x003399),
    'AFR':('Air France',0x002395),'KLM':('KLM',0x00A1DE),
    'UAE':('Emirates',0xCC0000),'THY':('Turkish',0xCC0000),
    'AUA':('Austrian',0xCC0000),'VLG':('Vueling',0xFF6600),
    'IBE':('Iberia',0xFF6600),'EWG':('Eurowings',0xFF6600),
    'EDW':('Edelweiss',0x00AAFF),'TAP':('TAP',0x00AA44),
    'SAS':('SAS',0x003399),'LOT':('LOT Polish',0x003399),
    'WZZ':('Wizz Air',0xC8007A),'TOM':('TUI',0x00539B),
    'CFG':('Condor',0xFFCC00),'TRA':('Transavia',0x00A650),
    'SXS':('SunExpress',0xFF6600),'BTI':('airBaltic',0x006400),
    'BOM':('Helvetic',0xCC0000),'QTR':('Qatar',0x6C1D45),
    'SIA':('Singapore',0xCC0000),'AAL':('American',0xCC0000),
    'UAL':('United',0x002395),'DAL':('Delta',0xCC0000),
    'ETH':('Ethiopian',0x007A4D),'TVS':('Smartwings',0xFF6600),
}

AIRPORT_INFO = {
    'ZRH':('Zurich','CH'),'GVA':('Geneva','CH'),'BSL':('Basel','CH'),
    'LHR':('Heathrow','GB'),'LGW':('Gatwick','GB'),'LCY':('City','GB'),
    'STN':('Stansted','GB'),'LTN':('Luton','GB'),'MAN':('Manchester','GB'),
    'EDI':('Edinburgh','GB'),'GLA':('Glasgow','GB'),'BHX':('Birmingham','GB'),
    'BRS':('Bristol','GB'),'NCL':('Newcastle','GB'),
    'FRA':('Frankfurt','DE'),'MUC':('Munich','DE'),'BER':('Berlin','DE'),
    'DUS':('Dusseldorf','DE'),'HAM':('Hamburg','DE'),'STR':('Stuttgart','DE'),
    'CGN':('Cologne','DE'),'NUE':('Nuremberg','DE'),
    'CDG':('De Gaulle','FR'),'ORY':('Orly','FR'),'NCE':('Nice','FR'),
    'LYS':('Lyon','FR'),'MRS':('Marseille','FR'),'TLS':('Toulouse','FR'),
    'BOD':('Bordeaux','FR'),'NTE':('Nantes','FR'),'LBG':('Le Bourget','FR'),
    'AMS':('Amsterdam','NL'),'EIN':('Eindhoven','NL'),
    'MAD':('Madrid','ES'),'BCN':('Barcelona','ES'),'PMI':('Palma','ES'),
    'AGP':('Malaga','ES'),'TFS':('Tenerife S','ES'),'LPA':('Gran Canaria','ES'),
    'ALC':('Alicante','ES'),'VLC':('Valencia','ES'),'IBZ':('Ibiza','ES'),
    'ACE':('Lanzarote','ES'),'FUE':('Fuerteventura','ES'),
    'FCO':('Rome','IT'),'MXP':('Milan Malpensa','IT'),'LIN':('Milan Linate','IT'),
    'VCE':('Venice','IT'),'NAP':('Naples','IT'),'PMO':('Palermo','IT'),
    'CTA':('Catania','IT'),'BLQ':('Bologna','IT'),'FLR':('Florence','IT'),
    'BGY':('Bergamo','IT'),'PSA':('Pisa','IT'),'VRN':('Verona','IT'),
    'LIS':('Lisbon','PT'),'OPO':('Porto','PT'),'FAO':('Faro','PT'),
    'FNC':('Funchal','PT'),
    'VIE':('Vienna','AT'),'GRZ':('Graz','AT'),'INN':('Innsbruck','AT'),'SZG':('Salzburg','AT'),
    'BRU':('Brussels','BE'),'CRL':('Charleroi','BE'),
    'CPH':('Copenhagen','DK'),'OSL':('Oslo','NO'),'ARN':('Stockholm','SE'),
    'GOT':('Gothenburg','SE'),'HEL':('Helsinki','FI'),
    'WAW':('Warsaw','PL'),'KRK':('Krakow','PL'),'GDN':('Gdansk','PL'),
    'PRG':('Prague','CZ'),'BTS':('Bratislava','SK'),'BUD':('Budapest','HU'),
    'ATH':('Athens','GR'),'HER':('Heraklion','GR'),'RHO':('Rhodes','GR'),
    'SKG':('Thessaloniki','GR'),'CFU':('Corfu','GR'),'JTR':('Santorini','GR'),
    'IST':('Istanbul','TR'),'SAW':('Sabiha','TR'),'AYT':('Antalya','TR'),
    'ADB':('Izmir','TR'),'DLM':('Dalaman','TR'),'BJV':('Bodrum','TR'),
    'DXB':('Dubai','AE'),'AUH':('Abu Dhabi','AE'),'DOH':('Doha','QA'),
    'TLV':('Tel Aviv','IL'),'AMM':('Amman','JO'),'BEY':('Beirut','LB'),
    'CAI':('Cairo','EG'),'RUH':('Riyadh','SA'),'JED':('Jeddah','SA'),
    'JFK':('New York JFK','US'),'LAX':('Los Angeles','US'),'MIA':('Miami','US'),
    'ORD':('Chicago','US'),'ATL':('Atlanta','US'),'SFO':('San Francisco','US'),
    'BOS':('Boston','US'),'DFW':('Dallas','US'),'EWR':('Newark','US'),
    'IAD':('Washington','US'),'SEA':('Seattle','US'),'DEN':('Denver','US'),
    'LAS':('Las Vegas','US'),'MCO':('Orlando','US'),
    'YYZ':('Toronto','CA'),'YVR':('Vancouver','CA'),'YUL':('Montreal','CA'),
    'NRT':('Tokyo Narita','JP'),'HND':('Tokyo Haneda','JP'),'KIX':('Osaka','JP'),
    'ICN':('Seoul','KR'),'HKG':('Hong Kong','HK'),'SIN':('Singapore','SG'),
    'BKK':('Bangkok','TH'),'HKT':('Phuket','TH'),
    'DEL':('Delhi','IN'),'BOM':('Mumbai','IN'),'BLR':('Bangalore','IN'),
    'PEK':('Beijing','CN'),'PVG':('Shanghai','CN'),
    'KUL':('Kuala Lumpur','MY'),'CGK':('Jakarta','ID'),'DPS':('Bali','ID'),
    'SYD':('Sydney','AU'),'MEL':('Melbourne','AU'),'BNE':('Brisbane','AU'),
    'AKL':('Auckland','NZ'),
    'JNB':('Johannesburg','ZA'),'CPT':('Cape Town','ZA'),
    'NBO':('Nairobi','KE'),'ADD':('Addis Ababa','ET'),
    'CMN':('Casablanca','MA'),'RAK':('Marrakech','MA'),
    'GRU':('Sao Paulo','BR'),'EZE':('Buenos Aires','AR'),'SCL':('Santiago','CL'),
    'BOG':('Bogota','CO'),'LIM':('Lima','PE'),
    'DUB':('Dublin','IE'),'KEF':('Reykjavik','IS'),'LUX':('Luxembourg','LU'),
    'MLA':('Malta','MT'),'LCA':('Larnaca','CY'),
    'OTP':('Bucharest','RO'),'SOF':('Sofia','BG'),'BEG':('Belgrade','RS'),
    'ZAG':('Zagreb','HR'),'DBV':('Dubrovnik','HR'),'SPU':('Split','HR'),
    'LJU':('Ljubljana','SI'),'SKP':('Skopje','MK'),'TIA':('Tirana','AL'),
    'RIX':('Riga','LV'),'TLL':('Tallinn','EE'),'VNO':('Vilnius','LT'),
    'SVO':('Moscow','RU'),'LED':('St Petersburg','RU'),
    'GYD':('Baku','AZ'),'TBS':('Tbilisi','GE'),'EVN':('Yerevan','AM'),
    'CUN':('Cancun','MX'),'MEX':('Mexico City','MX'),
    'MBJ':('Montego Bay','JM'),'PUJ':('Punta Cana','DO'),
    'AAC':('El Arish','EG'),'AAE':('Annaba','DZ'),'AAN':('Al Ain','AE'),
    'AAQ':('Krasnyi Kurg','RU'),'AAR':('Aarhus','DK'),'ABA':('Abakan','RU'),
    'ABB':('Asaba','NG'),'ABQ':('Albuquerque','US'),'ABV':('Abuja','NG'),
    'ABZ':('Aberdeen','GB'),'ACA':('Acapulco','MX'),'ACC':('Accra','GH'),
    'ACH':('St. Gallen','CH'),'ADA':('Seyhan','TR'),'ADF':('Adıyaman','TR'),
    'ADJ':('Amman','JO'),'ADL':('Adelaide','AU'),'ADZ':('San Andrés','CO'),
    'AEP':('Buenos Aires','AR'),'AER':('Sochi','RU'),'AES':('Ålesund','NO'),
    'AEY':('Akureyri','IS'),'AGA':('Al Massira','MA'),'AGH':('Ängelholm','SE'),
    'AGU':('Aguascalient','MX'),'AHB':('Abha','SA'),'AHO':('Alghero','IT'),
    'AJA':('Ajaccio','FR'),'AJF':('Al-Jawf','SA'),'AJI':('Ağrı','TR'),
    'AJR':('Arvidsjaur','SE'),'ALB':('Albany','US'),'ALF':('Alta','NO'),
    'ALG':('Algiers','DZ'),'AMD':('Ahmedabad','IN'),'AMQ':('Ambon','ID'),
    'AMV':('Amderma','RU'),'ANC':('Anchorage','US'),'ANF':('Antofagasta','CL'),
    'ANR':('Antwerp','BE'),'ANX':('Andenes','NO'),'AOE':('Eskişehir','TR'),
    'AOI':('Marche','IT'),'AOJ':('Aomori','JP'),'AOK':('Karpathos','GR'),
    'AQI':('Qaisumah','SA'),'AQJ':('Aqaba','JO'),'AQP':('Arequipa','PE'),
    'ARH':('Talagi','RU'),'ARW':('Arad','RO'),'ASF':('Astrakhan','RU'),
    'ASR':('Kayseri','TR'),'ASW':('Aswan','EG'),'ATQ':('Amritsar','IN'),
    'ATZ':('Asyut','EG'),'AUR':('Aurillac','FR'),'AUS':('Austin','US'),
    'AVN':('Avignon','FR'),'AVV':('Melbourne Av','AU'),'AWA':('Hawassa','ET'),
    'AXD':('Alexandroupo','GR'),'AZI':('Abu Dhabi','AE'),'BAH':('Manama','BH'),
    'BAL':('Batman','TR'),'BAQ':('Barranquilla','CO'),'BAV':('Baotou','CN'),
    'BAX':('Barnaul','RU'),'BAY':('Maramureș','RO'),'BBI':('Bhubaneswar','IN'),
    'BBU':('Bucharest','RO'),'BCD':('Bacolod City','PH'),'BCM':('Bacău','RO'),
    'BCU':('Bauchi','NG'),'BDJ':('Banjarbaru','ID'),'BDL':('Bradley','US'),
    'BDQ':('Vadodara','IN'),'BDS':('Brindisi','IT'),'BDU':('Målselv','NO'),
    'BEB':('Benbecula','GB'),'BEL':('Belém','BR'),'BEM':('Oulad Yaich','MA'),
    'BES':('Brest','FR'),'BFN':('Bloemfontein','ZA'),'BFS':('Belfast','GB'),
    'BGC':('Bragança','PT'),'BGO':('Bergen','NO'),'BHD':('Belfast','GB'),
    'BHM':('Birmingham','US'),'BHO':('Bhopal','IN'),'BIA':('Bastia','FR'),
    'BIO':('Bilbao','ES'),'BIQ':('Biarritz','FR'),'BJA':('Béjaïa','DZ'),
    'BJF':('Båtsfjord','NO'),'BJX':('Silao','MX'),'BJZ':('Badajoz','ES'),
    'BKI':('Kota Kinabal','MY'),'BLE':('Dala','SE'),'BLJ':('Batna','DZ'),
    'BLL':('Billund','DK'),'BMA':('Stockholm','SE'),'BME':('Broome','AU'),
    'BNA':('Nashville','US'),'BNN':('Brønnøy','NO'),'BNX':('Mahovljani','BA'),
    'BOH':('Bournemouth','GB'),'BOI':('Boise','US'),'BOJ':('Burgas','BG'),
    'BOO':('Bodø','NO'),'BPN':('Balikpapan','ID'),'BPS':('Porto Seguro','BR'),
    'BQS':('Ignatyevo','RU'),'BQT':('Brest','BY'),'BRC':('San Carlos d','AR'),
    'BRE':('Bremen','DE'),'BRI':('Bari','IT'),'BRN':('Bern','CH'),
    'BRQ':('Brno','CZ'),'BRR':('Barra','GB'),'BSB':('Brasília','BR'),
    'BSK':('Biskra','DZ'),'BTH':('Batam','ID'),'BTJ':('Banda Aceh','ID'),
    'BTK':('Bratsk','RU'),'BUF':('Buffalo','US'),'BUR':('Burbank','US'),
    'BUS':('Batumi','GE'),'BVA':('Beauvais','FR'),'BVB':('Boa Vista','BR'),
    'BVE':('Brive','FR'),'BVG':('Berlevåg','NO'),'BVJ':('Bovanenkovo','RU'),
    'BWI':('Baltimore','US'),'BWK':('Brač','HR'),'BWO':('Balakovo','RU'),
    'BZG':('Bydgoszcz','PL'),'BZI':('Balıkesir','TR'),'BZK':('Bryansk','RU'),
    'BZO':('Bolzano','IT'),'BZR':('Béziers','FR'),'CAG':('Cagliari','IT'),
    'CAL':('Campbeltown','GB'),'CAN':('Guangzhou Ba','CN'),'CAT':('Cascais','PT'),
    'CCF':('Carcassonne','FR'),'CCJ':('Calicut','IN'),'CCP':('Concepcion','CL'),
    'CCU':('Kolkata','IN'),'CDT':('Castellón de','ES'),'CEB':('Mactan Cebu','PH'),
    'CEE':('Cherepovets','RU'),'CEI':('Chiang Rai','TH'),'CEK':('Chelyabinsk','RU'),
    'CFE':('Clermont-Fer','FR'),'CFK':('Chlef','DZ'),'CFN':('Donegal','IE'),
    'CFR':('Caen','FR'),'CGB':('Cuiabá','BR'),'CGH':('São Paulo','BR'),
    'CGO':('Zhengzhou','CN'),'CGQ':('Changchun','CN'),'CGY':('Laguindingan','PH'),
    'CHC':('Christchurch','NZ'),'CHQ':('Souda','GR'),'CHS':('Charleston','US'),
    'CIA':('Rome','IT'),'CIX':('Chiclayo','PE'),'CIY':('Comiso','IT'),
    'CJB':('Coimbatore','IN'),'CJJ':('Cheongju','KR'),'CJS':('Ciudad Juáre','MX'),
    'CJU':('Jeju','KR'),'CKG':('Chongqing','CN'),'CKH':('Chokurdah','RU'),
    'CKZ':('Çanakkale','TR'),'CLE':('Cleveland','US'),'CLJ':('Cluj-Napoca','RO'),
    'CLO':('Cali','CO'),'CLT':('Charlotte','US'),'CLY':('Calvi','FR'),
    'CMF':('Chambéry','FR'),'CMH':('Columbus','US'),'CND':('Constanța','RO'),
    'CNF':('Belo Horizon','BR'),'CNN':('Kannur','IN'),'CNS':('Cairns','AU'),
    'CNX':('Chiang Mai','TH'),'COK':('Kochi','IN'),'COR':('Cordoba','AR'),
    'COS':('Colorado Spr','US'),'COV':('Tarsus','TR'),'CRA':('Craiova','RO'),
    'CRD':('Comodoro Riv','AR'),'CRK':('Mabalacat','PH'),'CRV':('Isola di Cap','IT'),
    'CSX':('Changsha Hua','CN'),'CSY':('Cheboksary','RU'),'CTG':('Cartagena','CO'),
    'CTS':('Sapporo','JP'),'CTU':('Chengdu Shua','CN'),'CUF':('Cuneo','IT'),
    'CUL':('Culiacán','MX'),'CUU':('Chihuahua','MX'),'CUZ':('Cusco','PE'),
    'CVG':('Cincinnati /','US'),'CWB':('Curitiba','BR'),'CWC':('Chernivtsi','UA'),
    'CWL':('Cardiff','GB'),'CXR':('Cam Ranh / C','VN'),'CYX':('Cherskiy','RU'),
    'CZL':('Constantine','DZ'),'CZM':('Cozumel','MX'),'DAD':('Da Nang','VN'),
    'DAT':('Datong','CN'),'DBB':('El Alamein','EG'),'DCA':('Washington','US'),
    'DCM':('Castres','FR'),'DEB':('Debrecen','HU'),'DHA':('Dhahran','SA'),
    'DIA':('Doha','QA'),'DIJ':('Dijon','FR'),'DIR':('Dire Dawa','ET'),
    'DIY':('Diyarbakır','TR'),'DJE':('Mellita','TN'),'DJG':('Djanet','DZ'),
    'DJJ':('Sentani','ID'),'DKR':('Dakar','SN'),'DLC':('Dalian Zhous','CN'),
    'DLE':('Dole','FR'),'DME':('Moscow','RU'),'DMK':('Bangkok','TH'),
    'DMM':('Ad Dammam','SA'),'DNA':('Okinawa','JP'),'DND':('Dundee','GB'),
    'DNH':('Dunhuang','CN'),'DNK':('Dnipro','UA'),'DNR':('Dinard','FR'),
    'DNZ':('Çardak','TR'),'DOL':('Deauville','FR'),'DQM':('Duqm','OM'),
    'DRP':('Bicol','PH'),'DRS':('Dresden','DE'),'DRW':('Darwin','AU'),
    'DSM':('Des Moines','US'),'DSN':('Ordos','CN'),'DSS':('Dakar','SN'),
    'DTM':('Dortmund','DE'),'DTW':('Detroit','US'),'DUR':('Durban','ZA'),
    'DVO':('Davao','PH'),'DWC':('Al Maktoum','AE'),'DXN':('Noida','IN'),
    'DYG':('Zhangjiajie ','CN'),'DYR':('Anadyr','RU'),'EAS':('Hondarribia','ES'),
    'EBA':('Marina di Ca','IT'),'EBJ':('Esbjerg','DK'),'ECN':('Ercan','CY'),
    'EDL':('Eldoret','KE'),'EDO':('Edremit','TR'),'EES':('Berenice Tro','EG'),
    'EFL':('Kefallinia','GR'),'EGC':('Bergerac','FR'),'EGO':('Belgorod','RU'),
    'EGS':('Egilsstaðir','IS'),'EHU':('Ezhou','CN'),'EIE':('Yeniseysk','RU'),
    'EIK':('Yeysk','RU'),'ELP':('El Paso','US'),'ELQ':('Qassim','SA'),
    'ELS':('King Phalo','ZA'),'EMA':('East Midland','GB'),'ENF':('Enontekio','FI'),
    'ENU':('Enegu','NG'),'EOI':('Eday','GB'),'EPU':('Pärnu','EE'),'ERC':('Erzincan','TR'),
    'ERF':('Erfurt','DE'),'ERZ':('Erzurum','TR'),'ESB':('Ankara','TR'),
    'ESL':('Elista','RU'),'ETM':('Eilat','IL'),'ETZ':('Goin','FR'),'EVE':('Evenes','NO'),
    'EXT':('Exeter','GB'),'EYK':('Beloyarskiy','RU'),'EZS':('Elazığ','TR'),
    'FAT':('Fresno','US'),'FCN':('Wurster Nord','DE'),'FDH':('Friedrichsha','DE'),
    'FEZ':('Saïss','MA'),'FJR':('Fujairah','AE'),'FKB':('Rheinmünster','DE'),
    'FLL':('Fort Lauderd','US'),'FLN':('Hercílio Luz','BR'),'FLW':('Flores','PT'),
    'FMM':('Memmingen','DE'),'FMO':('Greven','DE'),'FNI':('Nîmes/Garons','FR'),
    'FOC':('Fuzhou Chang','CN'),'FOG':('Foggia (FG)','IT'),'FOR':('Fortaleza','BR'),
    'FRL':('Forlì (FC)','IT'),'FRO':('Florø','NO'),'FSC':('Figari','FR'),
    'FSZ':('Mount Fuji S','JP'),'FTE':('El Calafate','AR'),'FUK':('Fukuoka','JP'),
    'GAU':('Guwahati','IN'),'GBB':('Gabala','AZ'),'GDL':('Guadalajara','MX'),
    'GDX':('Sokol','RU'),'GDZ':('Gelendzhik','RU'),'GEC':('Lefkoniko (G','CY'),
    'GEG':('Spokane','US'),'GES':('General Sant','PH'),'GEV':('Gällivare','SE'),
    'GHV':('Brașov-Ghimb','RO'),'GIG':('Rio De Janei','BR'),'GJL':('Tahir','DZ'),
    'GME':('Gomel','BY'),'GMP':('Seoul','KR'),'GNB':('Grenoble','FR'),'GNJ':('Ganja','AZ'),
    'GNY':('Şanlıurfa','TR'),'GOA':('Genova (GE)','IT'),'GOI':('Goa Dabolim','IN'),
    'GOJ':('Nizhny Novgo','RU'),'GOX':('Mopa','IN'),'GPA':('Patras','GR'),'GRJ':('George','ZA'),
    'GRO':('Girona','ES'),'GRQ':('Groningen','NL'),'GRR':('Grand Rapids','US'),
    'GRV':('Grozny','RU'),'GRW':('Graciosa','PT'),'GRX':('Granada','ES'),
    'GRY':('Grímsey','IS'),'GSO':('Greensboro','US'),'GSV':('Saratov','RU'),
    'GWT':('Sylt','DE'),'GYN':('Goiânia','BR'),'GZP':('Gazipaşa','TR'),
    'GZT':('Gaziantep','TR'),'HAD':('Halmstad','SE'),'HAJ':('Hannover','DE'),
    'HAK':('Haikou Meila','CN'),'HAN':('Noi Bai','VN'),'HAS':('Hail','SA'),
    'HAU':('Karmøy','NO'),'HBA':('Hobart','AU'),'HBE':('Alexandria','EG'),
    'HDF':('Zirchow','DE'),'HDY':('Hat Yai','TH'),'HET':('Hohhot','CN'),
    'HFE':('Hefei','CN'),'HFN':('Höfn','IS'),'HFT':('Hammerfest','NO'),
    'HGH':('Hangzhou','CN'),'HHN':('Frankfurt-Ha','DE'),'HIA':('Huaian','CN'),
    'HIJ':('Hiroshima','JP'),'HKD':('Hakodate','JP'),'HLA':('Lanseria','ZA'),
    'HLD':('Hailar','CN'),'HLP':('Jakarta','ID'),'HMA':('Khanty-Mansi','RU'),
    'HMB':('Suhaj','EG'),'HMO':('Hermosillo','MX'),'HNL':('Honolulu, Oa','US'),
    'HOF':('Hofuf','SA'),'HOR':('Horta','PT'),'HOU':('Houston','US'),
    'HOV':('Ørsta','NO'),'HPH':('Cat Bi','VN'),'HRB':('Harbin','CN'),
    'HRG':('Hurghada','EG'),'HSG':('Saga','JP'),'HSN':('Zhoushan','CN'),
    'HSR':('Rajkot','IN'),'HSS':('Hisar','IN'),'HTA':('Chita','RU'),
    'HTG':('Khatanga','RU'),'HTY':('Hatay','TR'),'HUX':('Huatulco','MX'),
    'HUY':('Humberside','GB'),'HVG':('Honningsvåg','NO'),'HWR':('Halwara','IN'),
    'HYD':('Hyderabad','IN'),'IAA':('Igarka','RU'),'IAH':('Houston','US'),
    'IAR':('Tunoshna','RU'),'IAS':('Iaşi','RO'),'IBR':('Omitama','JP'),
    'IDR':('Indore','IN'),'IEG':('Nowe Kramsko','PL'),'IEV':('Kyiv','UA'),
    'IFJ':('Ísafjörður','IS'),'IFO':('Ivano-Franki','UA'),'IGD':('Iğdır','TR'),
    'IGT':('Magas','RU'),'IGU':('Cataratas','BR'),'IJK':('Izhevsk','RU'),
    'IKS':('Tiksi','RU'),'IKT':('Irkutsk','RU'),'ILD':('Lleida','ES'),'ILO':('Iloilo','PH'),
    'ILR':('Ilorin/Ogbom','NG'),'ILY':('Islay','GB'),'IMF':('Imphal','IN'),
    'INC':('Yinchuan','CN'),'IND':('Indianapolis','US'),'INI':('Niš','RS'),
    'INV':('Inverness','GB'),'IOA':('Ioannina','GR'),'IPC':('Mataveri','CL'),
    'IPH':('Ipoh','MY'),'IQQ':('Iquique','CL'),'IQT':('Iquitos','PE'),
    'ISE':('Isparta','TR'),'ISK':('Nashik','IN'),'ISL':('İstanbul Ata','TR'),
    'ITM':('Osaka','JP'),'IVL':('Ivalo','FI'),'IWA':('Ivanovo','RU'),
    'IXB':('Siliguri','IN'),'IXC':('Chandigarh','IN'),'IXE':('Mangaluru','IN'),
    'IXZ':('Port Blair','IN'),'JAI':('Jaipur','IN'),'JAX':('Jacksonville','US'),
    'JCL':('České Budějo','CZ'),'JGN':('Jiayuguan','CN'),'JHB':('Senai','MY'),
    'JHG':('Jinghong (Ga','CN'),'JIJ':('Jijiga','ET'),'JJN':('Quanzhou','CN'),
    'JKG':('Jönköping','SE'),'JKH':('Chios Island','GR'),'JMK':('Mykonos','GR'),
    'JOE':('Joensuu','FI'),'JPA':('João Pessoa','BR'),'JSH':('Sitia','GR'),
    'JSI':('Skiathos','GR'),'JUJ':('San Salvador','AR'),'JUL':('Juliaca','PE'),
    'JYV':('Jyväskylä','FI'),'KAD':('Kaduna','NG'),'KAJ':('Kajaani','FI'),
    'KAN':('Kano','NG'),'KAO':('Kuusamo','FI'),'KBV':('Krabi','TH'),
    'KCH':('Kuching','MY'),'KCM':('Kahramanmara','TR'),'KCY':('Krasnoyarsk','RU'),
    'KCZ':('Nankoku','JP'),'KDL':('Kärdla','EE'),'KEJ':('Kemerovo','RU'),
    'KEM':('Kemi-Tornio','FI'),'KGD':('Khrabrovo','RU'),'KGP':('Kogalym','RU'),
    'KGS':('Kos Island','GR'),'KHE':('Kherson','UA'),'KHG':('Kashgar','CN'),
    'KHN':('Nanchang','CN'),'KHV':('Khabarovsk','RU'),'KIJ':('Niigata','JP'),
    'KIM':('Kimberley','ZA'),'KIN':('Kingston','JM'),'KIR':('Kerry','IE'),
    'KIS':('Kisumu','KE'),'KJA':('Krasnoyarsk','RU'),'KKJ':('Kitakyushu','JP'),
    'KKN':('Kirkenes','NO'),'KLO':('Kalibo','PH'),'KLR':('Kalmar','SE'),
    'KLU':('Klagenfurt','AT'),'KLV':('Karlovy Vary','CZ'),'KLX':('Kalamata','GR'),
    'KMG':('Kunming','CN'),'KMI':('Miyazaki','JP'),'KMJ':('Kumamoto','JP'),
    'KMQ':('Kanazawa','JP'),'KMS':('Kumasi','GH'),'KMW':('Kostroma','RU'),
    'KNO':('Beringin','ID'),'KOA':('Kailua-Kona','US'),'KOI':('Kirkwall','GB'),
    'KOJ':('Kagoshima','JP'),'KOK':('Kokkola / Kr','FI'),'KPW':('Keperveem','RU'),
    'KRF':('Nyland','SE'),'KRN':('Kiruna','SE'),'KRO':('Kurgan','RU'),
    'KRP':('Karup','DK'),'KRR':('Krasnodar','RU'),'KRS':('Kristiansand','NO'),
    'KSC':('Košice','SK'),'KSD':('Karlstad','SE'),'KSF':('Calden','DE'),
    'KSU':('Kvernberget','NO'),'KSY':('Kars','TR'),'KSZ':('Kotlas','RU'),
    'KTT':('Kittilä','FI'),'KTW':('Katowice','PL'),'KUF':('Samara','RU'),
    'KUN':('Kaunas','LT'),'KUO':('Kuopio','FI'),'KUT':('Kopitnari','GE'),
    'KVA':('Kavala','GR'),'KVO':('Morava','RS'),'KVX':('Kirov','RU'),
    'KWE':('Guiyang (Nan','CN'),'KWG':('Kryvyi Rih','UA'),'KWI':('Kuwait','KW'),
    'KWL':('Guilin (Ling','CN'),'KXK':('Komsomolsk-o','RU'),'KYA':('Konya','TR'),
    'KYZ':('Kyzyl','RU'),'KZI':('Kozani','GR'),'KZN':('Kazan','RU'),'LAO':('Laoag','PH'),
    'LBA':('Leeds Bradfo','GB'),'LBC':('Lübeck','DE'),'LCG':('A Coruña','ES'),
    'LCJ':('Łódź','PL'),'LDE':('Tarbes/Lourd','FR'),'LDY':('City of Derr','GB'),
    'LEI':('Almería','ES'),'LEJ':('Schkeuditz','DE'),'LEN':('León','ES'),
    'LEU':('Pirineus - l','ES'),'LGA':('New York','US'),'LGB':('Long Beach','US'),
    'LGG':('Liège','BE'),'LGK':('Langkawi','MY'),'LHL':('Lachin','AZ'),
    'LHW':('Lanzhou (Yon','CN'),'LIG':('Limoges','FR'),'LIH':('Lihue','US'),
    'LIL':('Lille','FR'),'LJG':('Lijiang','CN'),'LKL':('Lakselv','NO'),
    'LKN':('Leknes','NO'),'LKO':('Lucknow','IN'),'LLA':('Luleå','SE'),
    'LME':('Le Mans-Arna','FR'),'LMP':('Lampedusa','IT'),'LNZ':('Linz','AT'),
    'LOP':('Lombok','ID'),'LOS':('Lagos','NG'),'LPI':('Linköping','SE'),
    'LPK':('Lipetsk','RU'),'LPL':('Liverpool','GB'),'LPP':('Lappeenranta','FI'),
    'LPX':('Liepāja','LV'),'LRH':('La Rochelle','FR'),'LRM':('La Romana','DO'),
    'LRT':('Lorient/Lann','FR'),'LSI':('Sumburgh','GB'),'LTH':('Ho Chi Minh ','VN'),
    'LTO':('Loreto','MX'),'LUG':('Agno','CH'),'LUZ':('Lublin','PL'),
    'LWN':('Gyumri','AM'),'LWO':('Lviv','UA'),'LXA':('Lhasa Gongga','CN'),
    'LXR':('Luxor','EG'),'LYA':('Luoyang Beij','CN'),'LYC':('Lycksele','SE'),
    'LYG':('Lianyungang','CN'),'LYR':('Longyearbyen','NO'),'MAA':('Chennai','IN'),
    'MAH':('Menorca','ES'),'MAO':('Manaus','BR'),'MBA':('Moi','KE'),'MBX':('Maribor','SI'),
    'MCI':('Kansas City','US'),'MCT':('Muscat','OM'),'MCX':('Makhachkala','RU'),
    'MCY':('Maroochydore','AU'),'MCZ':('Maceió','BR'),'MDC':('Manado','ID'),
    'MDE':('Medellín','CO'),'MDW':('Chicago','US'),'MDZ':('Mendoza','AR'),
    'MED':('Medina','SA'),'MEH':('Mehamn','NO'),'MEM':('Memphis','US'),
    'MHG':('Mannheim','DE'),'MHQ':('Mariehamn','FI'),'MID':('Mérida','MX'),
    'MIU':('Maiduguri','NG'),'MJF':('Mosjøen','NO'),'MJT':('Mytilene','GR'),
    'MJZ':('Mirny','RU'),'MKE':('Milwaukee','US'),'MLM':('Morelia','MX'),
    'MLN':('Melilla','ES'),'MLX':('Malatya','TR'),'MME':('Teesside','GB'),
    'MMK':('Murmansk','RU'),'MMX':('Malmö','SE'),'MNL':('Ninoy Aquino','PH'),
    'MOL':('Årø','NO'),'MPL':('Montpellier/','FR'),'MPW':('Mariupol','UA'),
    'MQF':('Magnitogorsk','RU'),'MQJ':('Moma','RU'),'MQM':('Mardin','TR'),
    'MQN':('Mo i Rana','NO'),'MQP':('Mbombela','ZA'),'MRU':('Plaine Magni','MU'),
    'MRV':('Mineralnye V','RU'),'MSP':('Minneapolis','US'),'MSQ':('Minsk','BY'),
    'MSR':('Muş','TR'),'MST':('Maastricht','NL'),'MSY':('New Orleans','US'),
    'MTY':('Monterrey','MX'),'MUH':('Marsa Matruh','EG'),'MVQ':('Mogilev','BY'),
    'MWX':('Muan','KR'),'MXX':('Mora','SE'),'MYJ':('Matsuyama','JP'),
    'MYR':('Myrtle Beach','US'),'MZT':('Mazatlàn','MX'),'NAG':('Nagpur','IN'),
    'NAJ':('Nakhchivan','AZ'),'NAL':('Nalchik','RU'),'NAT':('Natal','BR'),
    'NAV':('Nevşehir','TR'),'NBC':('Begishevo','RU'),'NCY':('Annecy','FR'),
    'NDG':('Qiqihar','CN'),'NDR':('Al Aaroui','MA'),'NER':('Chulman','RU'),
    'NFG':('Nefteyugansk','RU'),'NGB':('Ningbo','CN'),'NGO':('Tokoname','JP'),
    'NGS':('Nagasaki','JP'),'NJC':('Nizhnevartov','RU'),'NKG':('Nanjing','CN'),
    'NKT':('Şırnak','TR'),'NLI':('Nikolayevsk-','RU'),'NLU':('Mexico City','MX'),
    'NMI':('Navi Mumbai','IN'),'NNG':('Nanning Wuxu','CN'),'NNM':('Naryan Mar','RU'),
    'NOC':('Charlestown','IE'),'NOJ':('Noyabrsk','RU'),'NOP':('Sinop','TR'),
    'NOZ':('Spichenkovo','RU'),'NQN':('Neuquén','AR'),'NQY':('Newquay','GB'),
    'NRK':('Norrköping','SE'),'NRN':('Weeze','DE'),'NSK':('Alykel','RU'),
    'NTL':('Newcastle','AU'),'NUM':('Sharma','SA'),'NUX':('Novy Urengoy','RU'),
    'NVT':('Navegantes','BR'),'NWI':('Norwich','GB'),'NYA':('Nyagan','RU'),
    'NYM':('Nadym','RU'),'NYO':('Nyköping','SE'),'OAK':('Oakland','US'),
    'OAX':('Oaxaca','MX'),'ODE':('Odense','DK'),'ODS':('Odesa','UA'),
    'OER':('Örnsköldsvik','SE'),'OGG':('Kahului','US'),'OGU':('Ordu','TR'),
    'OGZ':('Beslan','RU'),'OHD':('Ohrid','MK'),'OHO':('Okhotsk','RU'),
    'OHS':('Suhar','OM'),'OKA':('Naha','JP'),'OKC':('Oklahoma Cit','US'),
    'OKJ':('Okayama','JP'),'OLA':('Ørland','NO'),'OLB':('Olbia (SS)','IT'),
    'OLZ':('Olyokminsk','RU'),'OMA':('Omaha','US'),'OMO':('Mostar','BA'),
    'OMR':('Oradea','RO'),'OMS':('Omsk','RU'),'ONQ':('Zonguldak','TR'),
    'ONT':('Ontario','US'),'OOL':('Gold Coast','AU'),'ORB':('Örebro','SE'),
    'ORF':('Norfolk','US'),'ORK':('Cork','IE'),'ORN':('Es-Sénia','DZ'),
    'OSD':('Östersund','SE'),'OSI':('Osijek','HR'),'OSR':('Mošnov','CZ'),
    'OST':('Oostende','BE'),'OSW':('Orsk','RU'),'OUD':('Ahl Angad','MA'),
    'OUL':('Oulu','FI'),'OVB':('Novosibirsk','RU'),'OVD':('Ranón','ES'),
    'OVS':('Sovetskiy','RU'),'OZG':('Zagora','MA'),'OZH':('Zaporizhia','UA'),
    'OZZ':('Ouarzazate','MA'),'PAD':('Büren','DE'),'PBC':('Puebla','MX'),
    'PBI':('Palm Beach','US'),'PCL':('Pucallpa','PE'),'PDG':('Minangkabau','ID'),
    'PDL':('Ponta Delgad','PT'),'PDV':('Plovdiv','BG'),'PDX':('Portland','US'),
    'PED':('Pardubice','CZ'),'PEE':('Perm','RU'),'PEG':('Perugia (PG)','IT'),
    'PEN':('Penang','MY'),'PER':('Perth','AU'),'PES':('Petrozavodsk','RU'),
    'PEV':('Pécs','HU'),'PEX':('Pechora','RU'),'PEZ':('Penza','RU'),'PFO':('Paphos','CY'),
    'PGF':('Perpignan/Ri','FR'),'PHC':('Port Harcour','NG'),'PHE':('Port Hedland','AU'),
    'PHL':('Philadelphia','US'),'PHX':('Phoenix','US'),'PIE':('Pinellas Par','US'),
    'PIK':('Glasgow Pres','GB'),'PIO':('Pisco','PE'),'PIS':('Poitiers/Bia','FR'),
    'PIT':('Pittsburgh','US'),'PIX':('Pico','PT'),'PKC':('Yelizovo','RU'),
    'PKV':('Pskov','RU'),'PKX':('Beijing','CN'),'PLQ':('Palanga','LT'),
    'PLZ':('Chief Dawid ','ZA'),'PMC':('El Tepual','CL'),'PMF':('Parma','IT'),
    'PNA':('Pamplona','ES'),'PNK':('Supadio','ID'),'PNL':('Pantelleria','IT'),
    'PNQ':('Pune','IN'),'PNS':('Pensacola','US'),'POA':('Porto Alegre','BR'),
    'POR':('Pori','FI'),'POZ':('Poznań','PL'),'PPS':('Puerto Princ','PH'),
    'PQC':('Phú Quốc','VN'),'PRM':('Portimão','PT'),'PSD':('Port Said','EG'),
    'PSP':('Palm Springs','US'),'PSR':('Pescara','IT'),'PTG':('Polokwane','ZA'),
    'PUF':('Pau Pyrénées','FR'),'PUQ':('Punta Arenas','CL'),'PUS':('Busan','KR'),
    'PUY':('Pula','HR'),'PVD':('Providence/W','US'),'PVH':('Porto Velho','BR'),
    'PVK':('Preveza','GR'),'PVR':('Puerto Valla','MX'),'PWE':('Pevek','RU'),
    'PWM':('Portland','US'),'PXO':('Porto Santo','PT'),'PYJ':('Yakutia','RU'),
    'QRO':('Querétaro','MX'),'QSR':('Salerno','IT'),'RBA':('Rabat','MA'),
    'RBR':('Rio Branco','BR'),'RDO':('Radom','PL'),'RDU':('Raleigh/Durh','US'),
    'RDZ':('Rodez–Aveyro','FR'),'REC':('Recife','BR'),'REG':('Reggio Calab','IT'),
    'REN':('Orenburg','RU'),'RES':('Resistencia','AR'),'REU':('Reus','ES'),
    'RGL':('Rio Gallegos','AR'),'RIC':('Richmond','US'),'RJK':('Rijeka','HR'),
    'RKE':('Roskilde','DK'),'RKT':('Ras Al Khaim','AE'),'RKV':('Reykjavík','IS'),
    'RKZ':('Xigazê (Samz','CN'),'RLG':('Laage','DE'),'RMF':('Marsa Alam','EG'),
    'RMI':('Rimini (RN)','IT'),'RMU':('Corvera','ES'),'RMZ':('Tobolsk','RU'),
    'RNB':('Ronneby','SE'),'RNN':('Rønne','DK'),'RNO':('Reno','US'),
    'RNS':('Rennes-Saint','FR'),'ROC':('Rochester','US'),'ROS':('Rosario','AR'),
    'ROV':('Platov','RU'),'RRS':('Røros','NO'),'RSI':('Hanak','SA'),
    'RSW':('Fort Myers','US'),'RTM':('Rotterdam','NL'),'RUN':('Sainte-Marie','RE'),
    'RVK':('Rørvik','NO'),'RVN':('Rovaniemi','FI'),'RWN':('Rivne','UA'),
    'RYB':('Rybinsk','RU'),'RZE':('Jasionka','PL'),'RZV':('Rize','TR'),
    'SAG':('Kakadi','IN'),'SAN':('San Diego','US'),'SAT':('San Antonio','US'),
    'SAV':('Savannah','US'),'SBD':('San Bernardi','US'),'SBT':('Sabetta','RU'),
    'SBZ':('Sibiu','RO'),'SCN':('Saarbrücken','DE'),'SCQ':('Santiago de ','ES'),
    'SCR':('Malung-Sälen','SE'),'SCV':('Suceava','RO'),'SCW':('Syktyvkar','RU'),
    'SDF':('Louisville','US'),'SDJ':('Natori','JP'),'SDL':('Sundsvall-Hä','SE'),
    'SDQ':('Las Américas','DO'),'SDR':('Santander','ES'),'SDU':('Santos Dumon','BR'),
    'SEK':('Srednekolyms','RU'),'SEN':('London South','GB'),'SFB':('Orlando','US'),
    'SFS':('Olongapo','PH'),'SFT':('Skellefteå','SE'),'SGC':('Surgut','RU'),
    'SGD':('Sønderborg','DK'),'SGN':('Tan Son Nhat','VN'),'SHA':('Shanghai Hon','CN'),
    'SHE':('Shenyang','CN'),'SHJ':('Sharjah','AE'),'SIP':('Simferopol','UA'),
    'SJC':('San Jose','US'),'SJD':('Los Cabos','MX'),'SJJ':('Sarajevo','BA'),
    'SJW':('Shijiazhuang','CN'),'SJZ':('Velas','PT'),'SKN':('Hadsel','NO'),
    'SKO':('Sokoto','NG'),'SKX':('Saransk','RU'),'SLA':('Salta','AR'),
    'SLC':('Salt Lake Ci','US'),'SLD':('Sliač','SK'),'SLL':('Salalah','OM'),
    'SLM':('Salamanca','ES'),'SLY':('Salekhard','RU'),'SLZ':('São Luís','BR'),
    'SMA':('Santa Maria','PT'),'SMF':('Sacramento','US'),'SMI':('Samos','GR'),
    'SNA':('Santa Ana','US'),'SNN':('Shannon','IE'),'SNR':('Saint-Nazair','FR'),
    'SOB':('Sármellék','HU'),'SOC':('Surakarta','ID'),'SOJ':('Sørkjosen','NO'),
    'SOU':('Southampton','GB'),'SPC':('La Palma','ES'),'SPX':('Sphinx','EG'),
    'SRG':('Semarang','ID'),'SRP':('Leirvik','NO'),'SRQ':('Sarasota/Bra','US'),
    'SSA':('Salvador','BR'),'SSH':('Sharm El She','EG'),'SSJ':('Alstahaug','NO'),
    'STI':('Cibao','DO'),'STL':('St Louis','US'),'STV':('Surat','IN'),
    'STW':('Stavropol','RU'),'SUB':('Juanda','ID'),'SUF':('Lamezia Term','IT'),
    'SUI':('Sukhumi','GE'),'SUJ':('Satu Mare','RO'),'SVG':('Stavanger','NO'),
    'SVJ':('Svolvær','NO'),'SVL':('Savonlinna','FI'),'SVQ':('Seville','ES'),
    'SVX':('Koltsovo','RU'),'SWA':('Jieyang Chao','CN'),'SXB':('Strasbourg','FR'),
    'SXR':('Srinagar','IN'),'SYR':('Syracuse','US'),'SYS':('Saskylakh','RU'),
    'SYX':('Sanya Phoeni','CN'),'SYY':('Stornoway','GB'),'SZB':('Subang','MY'),
    'SZF':('Samsun','TR'),'SZX':('Shenzhen','CN'),'SZY':('Szymany','PL'),
    'SZZ':('Szczecin(Gle','PL'),'TAE':('Daegu','KR'),'TAK':('Takamatsu','JP'),
    'TAO':('Qingdao Jiao','CN'),'TAT':('Poprad','SK'),'TAY':('Tartu','EE'),
    'TEQ':('Çorlu','TR'),'TER':('Lajes','PT'),'TFN':('Tenerife','ES'),
    'TFU':('Chengdu Tian','CN'),'TGD':('Podgorica','ME'),'TGK':('Taganrog','RU'),
    'TGM':('Recea','RO'),'THN':('Trollhättan','SE'),'TIF':('Taif','SA'),
    'TIJ':('Tijuana','MX'),'TIR':('Tirupati','IN'),'TIV':('Tivat','ME'),
    'TJK':('Tokat','TR'),'TJM':('Tyumen','RU'),'TKS':('Tokushima','JP'),
    'TKU':('Turku','FI'),'TLC':('Toluca','MX'),'TLM':('Zenata','DZ'),
    'TLN':('Hyères, Var','FR'),'TML':('Tamale','GH'),'TMP':('Tampere-Pirk','FI'),
    'TMR':('Tamanrasset','DZ'),'TNA':('Jinan Yaoqia','CN'),'TNG':('Tangier','MA'),
    'TOF':('Tomsk','RU'),'TOS':('Tromsø','NO'),'TPA':('Tampa','US'),
    'TPS':('Trapani (TP)','IT'),'TQO':('Tulum','MX'),'TRD':('Trondheim','NO'),
    'TRE':('Tiree','GB'),'TRF':('Sandefjord(T','NO'),'TRN':('Turin','IT'),
    'TRS':('Trieste','IT'),'TRU':('Trujillo','PE'),'TRV':('Thiruvananth','IN'),
    'TRZ':('Tiruchirappa','IN'),'TSF':('Treviso','IT'),'TSN':('Tianjin','CN'),
    'TSR':('Timişoara','RO'),'TTU':('Tétouan','MA'),'TUC':('San Miguel d','AR'),
    'TUF':('Tours Val de','FR'),'TUL':('Tulsa','US'),'TUN':('Tunis','TN'),
    'TUS':('Tucson','US'),'TUU':('Tabuk','SA'),'TXN':('Huangshan','CN'),
    'TYF':('Torsby','SE'),'TYN':('Taiyuan','CN'),'TYS':('McGhee Tyson','US'),
    'TZL':('Tuzla','BA'),'TZX':('Trabzon','TR'),'UCT':('Ukhta','RU'),
    'UDJ':('Uzhhorod','UA'),'UFA':('Ufa','RU'),'UKB':('Kobe','JP'),
    'UKX':('Ust-Kut','RU'),'ULH':('Al-Ula','SA'),'ULK':('Lensk','RU'),
    'ULV':('Ulyanovsk','RU'),'ULY':('Cherdakly','RU'),'UME':('Umeå','SE'),
    'UPG':('Makassar','ID'),'URC':('Ürümqi','CN'),'URE':('Kuressaare','EE'),
    'URJ':('Uray','RU'),'URS':('Kursk','RU'),'USK':('Usinsk','RU'),'USM':('Samui','TH'),
    'USR':('Ust-Nera','RU'),'UTH':('Udon Thani','TH'),'UTP':('Rayong','TH'),
    'UUA':('Bugulma','RU'),'UUD':('Baikal','RU'),'UUS':('Yuzhno-Sakha','RU'),
    'VAA':('Vaasa','FI'),'VAN':('Van','TR'),'VAQ':('Vanavara','RU'),'VAR':('Varna','BG'),
    'VAW':('Vardø','NO'),'VBS':('Montichiari ','IT'),'VBY':('Visby','SE'),
    'VCA':('Can Tho','VN'),'VCP':('Campinas','BR'),'VDE':('El Hierro','ES'),
    'VDS':('Vadsø','NO'),'VEO':('Severo-Yenis','RU'),'VER':('Veracruz','MX'),
    'VGA':('Vijayawada','IN'),'VGO':('Vigo','ES'),'VHM':('Vilhelmina','SE'),
    'VIT':('Alava','ES'),'VIX':('Vitória','BR'),'VKO':('Moscow','RU'),
    'VKT':('Vorkuta','RU'),'VLL':('Valladolid','ES'),'VNS':('Varanasi','IN'),
    'VOG':('Volgograd','RU'),'VOL':('Nea Anchialo','GR'),'VOZ':('Voronezh','RU'),
    'VPN':('Vopnafjörður','IS'),'VRL':('Vila Real','PT'),'VSA':('Villahermosa','MX'),
    'VSE':('Viseu','PT'),'VST':('Stockholm Vä','SE'),'VTZ':('Visakhapatna','IN'),
    'VUS':('Velikiy Usty','RU'),'VVO':('Artyom','RU'),'VXO':('Växjö','SE'),
    'VYI':('Vilyuisk','RU'),'WIC':('Wick','GB'),'WLG':('Wellington','NZ'),
    'WMI':('Warsaw Modli','PL'),'WNZ':('Wenzhou Long','CN'),'WRO':('Wrocław','PL'),
    'WSI':('Sydney','AU'),'WTB':('Toowoomba','AU'),'WUH':('Wuhan Tianhe','CN'),
    'WUX':('Wuxi','CN'),'XCR':('Chalons en C','FR'),'XIY':('Xian','CN'),
    'XMN':('Xiamen','CN'),'XNN':('Xining Caoji','CN'),'XRY':('Jerez','ES'),
    'YCU':('Yuncheng Yan','CN'),'YEG':('Edmonton','CA'),'YEI':('Yenişehir','TR'),
    'YHZ':('Halifax','CA'),'YIA':('Yogyakarta','ID'),'YIW':('Yiwu','CN'),
    'YKO':('Hakkari','TR'),'YKS':('Yakutsk','RU'),'YLW':('Kelowna','CA'),
    'YNB':('Yanbu','SA'),'YNT':('Yantai','CN'),'YNY':('Yangyang','KR'),
    'YNZ':('Yancheng Nan','CN'),'YOW':('Ottawa','CA'),'YQB':('Quebec','CA'),
    'YWG':('Winnipeg','CA'),'YXE':('Saskatoon','CA'),'YYC':('Calgary','CA'),
    'YYJ':('Victoria','CA'),'YYT':('St. Johns','CA'),'ZAD':('Zadar','HR'),
    'ZAM':('Zamboanga','PH'),'ZAZ':('Zaragoza','ES'),'ZCO':('Temuco','CL'),
    'ZHA':('Zhanjiang','CN'),'ZIA':('Moscow','RU'),'ZIH':('Ixtapa','MX'),
    'ZIX':('Zhigansk','RU'),'ZKP':('Zyryanka','RU'),'ZQN':('Queenstown','NZ'),
    'ZSE':('Saint-Pierre','RE'),'ZTH':('Zakynthos','GR'),'ZUH':('Zhuhai Jinwa','CN'),
}

AIRCRAFT_NAMES = {
    # Airbus Narrow
    'A318':'Airbus A318','A319':'Airbus A319','A320':'Airbus A320',
    'A321':'Airbus A321','A20N':'Airbus A320neo','A21N':'Airbus A321neo',
    'A19N':'Airbus A319neo','A223':'Airbus A220-300','A225':'Airbus A220',
    # Airbus Wide
    'A306':'Airbus A300','A310':'Airbus A310',
    'A332':'Airbus A330-200','A333':'Airbus A330-300',
    'A338':'Airbus A330-800neo','A339':'Airbus A330-900neo',
    'A342':'Airbus A340-200','A343':'Airbus A340-300',
    'A345':'Airbus A340-500','A346':'Airbus A340-600',
    'A359':'Airbus A350-900','A35K':'Airbus A350-1000','A388':'Airbus A380',
    # Airbus A220
    'BCS1':'Airbus A220-100','BCS3':'Airbus A220-300',
    # Boeing Narrow
    'B732':'Boeing 737-200','B733':'Boeing 737-300',
    'B734':'Boeing 737-400','B735':'Boeing 737-500',
    'B736':'Boeing 737-600','B737':'Boeing 737-700',
    'B738':'Boeing 737-800','B739':'Boeing 737-900',
    'B37M':'Boeing 737 MAX 7','B38M':'Boeing 737 MAX 8',
    'B39M':'Boeing 737 MAX 9','B3XM':'Boeing 737 MAX 10',
    # Boeing Wide
    'B741':'Boeing 747-100','B742':'Boeing 747-200',
    'B743':'Boeing 747-300','B744':'Boeing 747-400',
    'B748':'Boeing 747-8','B74S':'Boeing 747SP',
    'B752':'Boeing 757-200','B753':'Boeing 757-300',
    'B762':'Boeing 767-200','B763':'Boeing 767-300',
    'B764':'Boeing 767-400','B772':'Boeing 777-200',
    'B77L':'Boeing 777-200LR','B77W':'Boeing 777-300ER',
    'B778':'Boeing 777X-8','B779':'Boeing 777X-9',
    'B788':'Boeing 787-8','B789':'Boeing 787-9','B78X':'Boeing 787-10',
    # Embraer Jets
    'E135':'Embraer ERJ-135','E145':'Embraer ERJ-145',
    'E170':'Embraer 170','E175':'Embraer 175',
    'E17S':'Embraer E175 E2','E190':'Embraer 190',
    'E195':'Embraer 195','E290':'Embraer E190 E2',
    'E295':'Embraer E195 E2',
    'E75L':'Embraer E175 L','E75S':'Embraer E175 S',
    # Bombardier CRJ
    'CRJ1':'CRJ-100','CRJ2':'CRJ-200',
    'CRJ7':'CRJ-700','CRJ9':'CRJ-900','CRJX':'CRJ-1000',
    # Bombardier Dash 8
    'DH8A':'Dash 8-100','DH8B':'Dash 8-200',
    'DH8C':'Dash 8-300','DH8D':'Dash 8 Q400',
    # ATR
    'AT43':'ATR 42-300','AT45':'ATR 42-500',
    'AT72':'ATR 72-200','AT73':'ATR 72-300',
    'AT75':'ATR 72-500','AT76':'ATR 72-600',
    # McDonnell Douglas
    'MD11':'MD-11','MD81':'MD-81','MD82':'MD-82',
    'MD83':'MD-83','MD87':'MD-87','MD88':'MD-88',
    'MD90':'MD-90','DC10':'DC-10','DC93':'DC-9-30',
    # Cessna
    'C172':'Cessna 172','C182':'Cessna 182',
    'C208':'Cessna Caravan','C210':'Cessna 210',
    'C310':'Cessna 310','C340':'Cessna 340',
    'C402':'Cessna 402','C404':'Cessna 404',
    'C414':'Cessna 414','C421':'Cessna 421',
    # Citation
    'C500':'Citation I','C501':'Citation I SP',
    'C510':'Citation Mustang','C525':'Citation CJ',
    'C526':'Citation CJ1+','C527':'Citation CJ2',
    'C550':'Citation II','C551':'Citation II SP',
    'C56X':'Citation XLS','C560':'Citation V',
    'C650':'Citation III','C680':'Citation Sovereign',
    'C68A':'Citation Sovereign+','C700':'Citation Longitude',
    'C750':'Citation X',
    # Piper
    'PA18':'Piper Cub','PA24':'Piper Comanche',
    'PA28':'Piper Cherokee','PA32':'Piper Cherokee Six',
    'PA34':'Piper Seneca','PA44':'Piper Seminole',
    'PA46':'Piper Malibu','PA60':'Piper Aerostar',
    # Other GA
    'SR20':'Cirrus SR20','SR22':'Cirrus SR22',
    'DA40':'Diamond DA40','DA42':'Diamond DA42',
    'DA62':'Diamond DA62',
    'TBM7':'TBM 700','TBM8':'TBM 850','TBM9':'TBM 900',
    'PC12':'Pilatus PC-12','PC24':'Pilatus PC-24',
    'BE20':'King Air 200','BE30':'King Air 300',
    'BE35':'Bonanza','BE36':'Bonanza A36',
    'BE58':'Baron 58','BE9L':'King Air 90',
    'SF34':'Saab 340',
    # Bombardier Business Jets
    'CL30':'Challenger 300','CL35':'Challenger 350',
    'CL60':'Challenger 600','CL64':'Challenger 604',
    'CL65':'Challenger 605','CL75':'Challenger 650',
    'GL5T':'Gulfstream G500','GLEX':'Global Express',
    'GLF4':'Gulfstream G-IV','GLF5':'Gulfstream G-V',
    'GLF6':'Gulfstream G650',
    'GL7T':'Global 7500',
    # Gulfstream
    'G150':'Gulfstream G150','G280':'Gulfstream G280',
    'GALX':'Gulfstream Galaxy',
    # Dassault
    'F2TH':'Falcon 2000','F900':'Falcon 900',
    'F9EX':'Falcon 900EX','FA50':'Falcon 50',
    'FA7X':'Falcon 7X','FA8X':'Falcon 8X',
    # Embraer Business Jets
    'E50P':'Phenom 100','E55P':'Phenom 300',
    'E545':'Legacy 450','E550':'Legacy 500',
    # Learjet
    'LJ25':'Learjet 25','LJ35':'Learjet 35',
    'LJ40':'Learjet 40','LJ45':'Learjet 45',
    'LJ55':'Learjet 55','LJ60':'Learjet 60',
    'LJ70':'Learjet 70','LJ75':'Learjet 75',
    # Other Business Jets
    'H25B':'BAe 125-800','H25C':'BAe 125-1000',
    'HDJT':'HondaJet','PRM1':'Beechcraft Premier',
    'P180':'Piaggio Avanti',
}

HELI_TYPES = {
    'EC30','EC35','EC45','EC55','EC75','EC20','EC25', # Eurocopter/Airbus Helicopters
    'AS32','AS35','AS50','AS55','AS65', # AgustaWestland/Leonardo
    'BO10','BO50','B429', # Bell
    'S076','S092','S76','S92', # Sikorsky
    'R44','R66', # Robinson
    'H1','H47','H60','H64','H72', # Boeing Vertol/McDonnell Douglas
    'A109','A119','A139','A169','A189', # AgustaWestland/Leonardo
    'B06','B07','B47','B21','B06', # Boeing Vertol/McDonnell Douglas
    'MD52','MD60', # McDonnell Douglas
    'MH65','MH60', # US Coast Guard Helicopters
}

# Airline livery: (fuselage_colour, tail_colour)
LIVERIES = {
    'SWR':  (0xFFFFFF, 0xFF0000),   # Swiss - white body red tail
    'OAW':  (0xFFFFFF, 0xFF0000),
    'DLH':  (0xFFFFFF, 0xFFCC00),   # Lufthansa - white body yellow tail
    'BAW':  (0xFFFFFF, 0x003399),   # BA - white body blue tail
    'EZY':  (0xFF6600, 0xFF6600),   # easyJet - all orange
    'RYR':  (0xFFFFFF, 0x003399),   # Ryanair - white body blue tail
    'AFR':  (0xFFFFFF, 0x002395),   # Air France - white body blue tail
    'KLM':  (0xFFFFFF, 0x00A1DE),   # KLM - white body light blue tail
    'UAE':  (0xFFFFFF, 0xCC0000),   # Emirates - white body red tail
    'THY':  (0xFFFFFF, 0xCC0000),   # Turkish - white body red tail
    'AUA':  (0xFFFFFF, 0xCC0000),   # Austrian - white body red tail
    'VLG':  (0xFFFF00, 0xFF6600),   # Vueling - yellow body orange tail
    'IBE':  (0xFFFFFF, 0xFF6600),   # Iberia - white body orange tail
    'EWG':  (0xFFFFFF, 0xCC00CC),   # Eurowings - white body purple tail
    'EDW':  (0xFFFFFF, 0xCC0000),   # Edelweiss - white body red tail
    'TAP':  (0xFFFFFF, 0x00AA44),   # TAP - white body green tail
    'SAS':  (0xFFFFFF, 0x003399),   # SAS - white body blue tail
    'WZZ':  (0xFF00CC, 0xFF00CC),   # Wizz - all magenta
    'TOM':  (0xFFFFFF, 0x00539B),   # TUI - white body blue tail
    'QTR':  (0xFFFFFF, 0x6C1D45),   # Qatar - white body maroon tail
    'SIA':  (0xFFFFFF, 0xFFD700),   # Singapore - white body gold tail
    'BTI':  (0x00AA00, 0x004400),   # airBaltic - green
    'SXS':  (0xFF6600, 0xFF0000),   # SunExpress - orange/red
    'BOM':  (0xFFFFFF, 0xCC0000),   # Helvetic - white body red tail
    # Scandinavian
    'FIN':  (0xFFFFFF, 0x003399),   # Finnair - white body blue tail
    'NAX':  (0xCC0000, 0xCC0000),   # Norwegian - red
    'BRA':  (0xFFFFFF, 0x006600),   # Braathens - white/green
    # Middle East / Asia
    'SVA':  (0x006600, 0x006600),   # Saudia - green
    'GFA':  (0xCC0000, 0x8B0000),   # Gulf Air - red/maroon
    'OMA':  (0xCC0000, 0x8B0000),   # Oman Air - red
    'MSR':  (0x003399, 0x003399),   # EgyptAir - blue
    'ELY':  (0xFFFFFF, 0x003399),   # El Al - white/blue
    'THA':  (0xFFFFFF, 0x6A0DAD),   # Thai - white/purple
    'MAS':  (0x003399, 0xCC0000),   # Malaysia - blue/red
    'SIA':  (0xFFFFFF, 0xFFD700),   # Singapore - white/gold
    'CPA':  (0xFFFFFF, 0x006600),   # Cathay - white/green
    'ANA':  (0xFFFFFF, 0x003399),   # ANA - white/blue
    'JAL':  (0xFFFFFF, 0xCC0000),   # JAL - white/red
    'KAL':  (0xFFFFFF, 0x003399),   # Korean Air - white/blue
    'AAR':  (0xFFFFFF, 0x00AAFF),   # Asiana - white/light blue
    'CCA':  (0xCC0000, 0xCC0000),   # Air China - red
    'CSN':  (0xFFFFFF, 0x003399),   # China Southern - white/blue
    'CES':  (0xFFFFFF, 0xCC0000),   # China Eastern - white/red
    'AIC':  (0xCC0000, 0xFF6600),   # Air India - red/orange
    # North America
    'AAL':  (0xFFFFFF, 0x003399),   # American - white/blue
    'UAL':  (0xFFFFFF, 0x003399),   # United - white/blue
    'DAL':  (0xFFFFFF, 0xCC0000),   # Delta - white/red
    'SWA':  (0xFF6600, 0xCC0000),   # Southwest - orange/red
    'JBU':  (0xFFFFFF, 0x0033A0),   # JetBlue - white/blue
    'WN':   (0xFF6600, 0xCC0000),   # Southwest - orange/red
    'ACA':  (0xCC0000, 0xCC0000),   # Air Canada - red
    'WJA':  (0xFFFFFF, 0x00AA44),   # WestJet - white/green
    # South America
    'LAN':  (0xFFFFFF, 0xCC0000),   # LATAM - white/red
    'TAM':  (0xFFFFFF, 0xCC0000),   # LATAM Brazil - white/red
    'AVA':  (0xCC0000, 0xFF6600),   # Avianca - red/orange
    'GLO':  (0xFF6600, 0xFF6600),   # Gol - orange
    # Africa / Other
    'ETH':  (0x006600, 0xFFD700),   # Ethiopian - green/gold
    'KQA':  (0xCC0000, 0x006600),   # Kenya Airways - red/green
    'SAA':  (0xFFFFFF, 0x003399),   # South African - white/blue
    'RAM':  (0x006600, 0xCC0000),   # Royal Air Maroc - green/red
    # Low cost Europe
    'VLG':  (0xFFFF00, 0xFF6600),   # Vueling - yellow/orange
    'VKG':  (0xFF6600, 0xFF6600),   # Thomas Cook - orange
    'CFG':  (0xFFFF00, 0xFFFF00),   # Condor - yellow
    'TRA':  (0x00AA44, 0x00AA44),   # Transavia - green
    'HV':   (0x00AA44, 0x00AA44),   # Transavia NL - green
    'TVS':  (0xFF6600, 0xFF6600),   # Smartwings - orange
    'CSE':  (0xFF0000, 0xFF0000),   # PrivatAir - red
    'LGL':  (0xFFFFFF, 0xCC0000),   # Luxair - white/red
    'AUA':  (0xFFFFFF, 0xCC0000),   # Austrian - white/red
}

WEATHER_CODES = {
    0:'Clear',1:'Mostly Clear',2:'Partly Cloudy',3:'Overcast',
    45:'Fog',48:'Fog',51:'Drizzle',53:'Drizzle',55:'Drizzle',
    61:'Light Rain',63:'Rain',65:'Heavy Rain',
    71:'Light Snow',73:'Snow',75:'Heavy Snow',
    80:'Showers',81:'Showers',82:'Heavy Showers',
    95:'Thunder',96:'Thunder',99:'Thunder',
}


def lookup_airline_hex(hex_code, requests_session):
    """Look up airline/operator from ICAO hex code via hexdb.io"""
    try:
        url = HEXDB_URL + hex_code.upper()
        resp = requests_session.get(url)
        if resp.status_code == 200:
            data = resp.json()
            operator = data.get("OperatorFlagCode","") or data.get("Operator","")
            reg = data.get("Registration","")
            return operator.strip(), reg.strip()
    except Exception as e:
        print("hexdb error:", e)
    return "", ""


def lookup_planespotters(hex_code, requests_session):
    """Get operator for private/bizjet from planespotters.net - free, no key."""
    try:
        resp = requests_session.get(
            PLANESPOTTERS_URL + hex_code.upper(),
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=8
        )
        if resp.status_code == 200:
            ac = resp.json().get("aircraft", [])
            if ac:
                a = ac[0]
                operator = a.get("operator","") or a.get("airline",{}).get("name","")
                reg      = a.get("registration","")
                iata     = a.get("airline",{}).get("iata","")
                return operator.strip(), reg.strip(), iata.strip()
    except Exception as e:
        print("Planespotters:", e)
    return "", "", ""


def lookup_opensky(hex_code, requests_session):
    """Get operator/registration from OpenSky - free, no key."""
    try:
        resp = requests_session.get(OPENSKY_URL + hex_code.lower())
        if resp.status_code == 200:
            states = resp.json().get("states", [])
            if states:
                s = states[0]
                # [0]=icao24 [1]=callsign [2]=origin_country [7]=baroalt
                # [8]=onground [13]=squawk [14]=spi [15]=position_source
                callsign = (s[1] or "").strip()
                country  = s[2] or ""
                return callsign, country
    except Exception as e:
        print("OpenSky:", e)
    return "", ""


def enrich_from_adsb(hex_code, requests_session):
    """Fetch extra flight info from adsb.lol using ICAO hex"""
    try:
        resp = requests_session.get(ADSB_URL + hex_code.upper())
        if resp.status_code == 200:
            data = resp.json()
            ac = data.get("ac", [])
            if ac:
                a = ac[0]
                return {
                    "reg":       a.get("r",""),
                    "operator":  a.get("ownOp","") or a.get("man",""),
                    "origin":    a.get("orig",""),
                    "dest":      a.get("dest",""),
                    "flight":    a.get("flight","").strip(),
                    "aircraft":  a.get("t",""),
                    "alt":       a.get("alt_baro",0) or 0,
                    "speed":     a.get("gs",0) or 0,
                }
    except Exception as e:
        print("ADSB error:", e)
    return {}


def speed_to_delay(kts):
    if kts < 200: return 0.07
    if kts < 350: return 0.045
    if kts < 500: return 0.025
    return 0.015


def plane_colour_for(aircraft):
    a = aircraft.upper()
    if a.startswith('B') and len(a)==4: return 0xFFFFFF
    if a.startswith('A') and len(a)==4: return 0xFFD700
    return PLANE_COLOUR


# ---- Hardware ----
status_light = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
matrixportal = MatrixPortal(headers=rheaders, rotation=0, debug=False)

_plane_speed_delay = 0.03
_plane_speed_knots = 0
_is_a380 = False
_current_airline = ''


def make_plane_bmp(airline=''):
    livery = LIVERIES.get(airline, (0xDDDDDD, PLANE_COLOUR))
    fuselage, tail = livery
    W,H = 40,20
    bmp = displayio.Bitmap(W,H,4)
    pal = displayio.Palette(4)
    pal[0]=0x000000; pal[1]=fuselage; pal[2]=tail; pal[3]=0x88CCFF
    def p(x,y,c):
        if 0<=x<W and 0<=y<H: bmp[x,y]=c
    def row(x1,x2,y,c):
        for x in range(x1,x2+1): p(x,y,c)
    # Tail fin - pointed
    p(0,0,2);
    row(0,1,1,2); row(0,2,2,2); row(0,3,3,2); row(0,4,3,2)
    row(0,4,5,2); row(0,4,6,2)
    # Fin base merges into fuselage
    row(0,4,7,2)
    # Fuselage top
    row(1,38,7,1)
    # Fuselage body
    row(0,38,8,1); row(0,38,9,1); row(0,38,10,1); row(0,38,11,1)
    # Fuselage bottom
    row(1,38,12,1)
    # Nose
    p(39,8,1); p(39,9,1); p(39,10,1); p(39,11,1)
    # Upper wing - wider triangle flush to fuselage top
    row(11,24,7,1)   # root at fuselage top
    row(9,22,6,1)
    row(8,20,5,1)
    row(7,18,4,1)
    row(7,15,3,1)
    row(7,13,2,1)
    row(7,10,1,1)
    p(7,0,1)
    # Lower wing - wider triangle flush to fuselage bottom
    row(11,24,12,1)  # root at fuselage bottom
    row(9,22,13,1)
    row(8,20,14,1)
    row(7,18,15,1)
    row(7,15,16,1)
    row(7,13,17,1)
    row(7,10,18,1)
    p(7,19,1)
    # Rear horizontal stabs
    row(0,7,13,2); row(0,6,14,2); row(0,4,15,2); row(1,3,16,2)
    # Windows
    for wx in [20,22,24,26,28,30,32,34,36]:
        p(wx,9,3)
    # Swiss cross on tail fin
    if airline in ('SWR','OAW'):
        pal[3] = 0xFFFFFF
        # Vertical bar of cross
        p(2,2,3); p(2,3,3); p(2,4,3); p(2,5,3)
        # Horizontal bar of cross
        p(1,3,3); p(2,3,3); p(3,3,3)
    return bmp,pal


def make_landing_bmp(airline=''):
    livery = LIVERIES.get(airline, (0xDDDDDD, PLANE_COLOUR))
    fuselage, tail = livery
    W,H = 40,20
    bmp = displayio.Bitmap(W,H,4)
    pal = displayio.Palette(4)
    pal[0]=0x000000; pal[1]=fuselage; pal[2]=tail; pal[3]=0x88CCFF
    def p(x,y,c):
        if 0<=x<W and 0<=y<H: bmp[x,y]=c
    def row(x1,x2,y,c):
        for x in range(x1,x2+1): p(x,y,c)
    # Mirror: tail fin on right side
    p(39,0,2)
    row(38,39,1,2); row(37,39,2,2); row(36,39,3,2); row(35,39,4,2)
    row(35,39,5,2); row(35,39,6,2); row(35,39,7,2)
    # Fuselage top
    row(1,38,7,1)
    # Fuselage body
    row(1,39,8,1); row(1,39,9,1); row(1,39,10,1); row(1,39,11,1)
    # Fuselage bottom
    row(1,38,12,1)
    # Nose on left
    p(0,8,1); p(0,9,1); p(0,10,1); p(0,11,1)
    # Upper wing (mirrored)
    row(15,28,7,1)
    row(17,30,6,1)
    row(19,31,5,1)
    row(21,32,4,1)
    row(24,32,3,1)
    row(26,32,2,1)
    row(29,32,1,1)
    p(32,0,1)
    # Lower wing (mirrored)
    row(15,28,12,1)
    row(17,30,13,1)
    row(19,31,14,1)
    row(21,32,15,1)
    row(24,32,16,1)
    row(26,32,17,1)
    row(29,32,18,1)
    p(32,19,1)
    # Rear stabs on right
    row(32,39,13,2); row(33,39,14,2); row(35,39,15,2); row(36,38,16,2)
    # Windows
    for wx in [3,5,7,9,11,13,15,17,19]:
        p(wx,9,3)
    # Swiss cross on tail fin (mirrored, tail is on right at x=35-39)
    if airline in ('SWR','OAW'):
        pal[3] = 0xFFFFFF
        p(37,2,3); p(37,3,3); p(37,4,3); p(37,5,3)
        p(36,3,3); p(37,3,3); p(38,3,3)
    return bmp,pal


def setup_plane(aircraft, speed_knots, airline=''):
    global _plane_speed_delay, _plane_speed_knots, _is_a380, _current_airline
    _plane_speed_delay = speed_to_delay(speed_knots)
    _plane_speed_knots = speed_knots
    _is_a380 = (aircraft.upper() == 'A388')
    _current_airline = airline

def make_anim_group(landing=False):
    bmp,pal = make_landing_bmp(_current_airline) if landing else make_plane_bmp(_current_airline)
    tg = displayio.TileGrid(bmp, pixel_shader=pal)
    spd = adafruit_display_text.label.Label(FONT,color=0xAAAAAA,text=str(_plane_speed_knots)+"kt")
    spd.x=1; spd.y=27
    pg = displayio.Group()
    pg.append(tg)
    pg.append(spd)
    return pg, tg

def plane_animation():
    pg, tg = make_anim_group(False)
    matrixportal.display.root_group = pg
    tg.y = matrixportal.display.height//2 - 6
    for i in range(-40, matrixportal.display.width+40):
        tg.x=i; wfeed(); time.sleep(_plane_speed_delay)
    matrixportal.display.root_group = g
    gc.collect()

def make_runway_bmp(width, side='left'):
    # Runway: 8px tall with tarmac, edge lines and centre dashes
    h = 8
    bmp = displayio.Bitmap(width, h, 4)
    pal = displayio.Palette(4)
    pal[0] = 0x000000  # black bg
    pal[1] = 0x444444  # dark grey tarmac
    pal[2] = 0xFFFFFF  # white edge lines
    pal[3] = 0xFFFF00  # yellow centre dashes
    # Tarmac fill
    for y in range(1, h):
        for x in range(width):
            bmp[x, y] = 1
    # White edge lines top and bottom of runway
    for x in range(width):
        bmp[x, 1] = 2
        bmp[x, h-1] = 2
    # Centre yellow dashes every 8px, 4px long
    cy = h // 2
    for x in range(0, width, 8):
        for dx in range(4):
            if x+dx < width:
                bmp[x+dx, cy] = 3
    # Threshold markers at start (takeoff) or end (landing)
    if side == 'left':
        for y in range(2, h-1, 2):
            for dx in range(3):
                if dx < width:
                    bmp[dx, y] = 2
    else:
        for y in range(2, h-1, 2):
            for dx in range(3):
                if width-1-dx >= 0:
                    bmp[width-1-dx, y] = 2
    return bmp, pal

def plane_animation_take_off():
    rw_bmp, rw_pal = make_runway_bmp(matrixportal.display.width, 'left')
    rw_tg = displayio.TileGrid(rw_bmp, pixel_shader=rw_pal, x=0, y=24)
    bmp, pal = make_plane_bmp(_current_airline)
    ptg = displayio.TileGrid(bmp, pixel_shader=pal)
    spd = adafruit_display_text.label.Label(FONT, color=0xAAAAAA, text=str(_plane_speed_knots)+"kt")
    spd.x=1; spd.y=4
    pg = displayio.Group()
    pg.append(rw_tg); pg.append(ptg); # pg.append(spd)
    matrixportal.display.root_group = pg
    steps = matrixportal.display.width+24
    for i in range(steps):
        ptg.x=-40+i
        ptg.y=8-(i*10//steps)
        wfeed(); time.sleep(_plane_speed_delay)
        if ptg.x>matrixportal.display.width or ptg.y<-20: break
    matrixportal.display.root_group = g
    gc.collect()

def plane_animation_landing():
    rw_bmp, rw_pal = make_runway_bmp(matrixportal.display.width, 'right')
    rw_tg = displayio.TileGrid(rw_bmp, pixel_shader=rw_pal, x=0, y=24)
    bmp, pal = make_landing_bmp(_current_airline)
    ltg = displayio.TileGrid(bmp, pixel_shader=pal)
    spd = adafruit_display_text.label.Label(FONT, color=0xAAAAAA, text=str(_plane_speed_knots)+"kt")
    spd.x=1; spd.y=4
    pg = displayio.Group()
    pg.append(rw_tg); pg.append(ltg); # pg.append(spd)
    matrixportal.display.root_group = pg
    # Nose-first: enter upper-right, descend steeply to runway level lower-left
    steps = matrixportal.display.width + 40
    for i in range(steps):
        # x moves right to left: starts off right edge, ends off left edge
        ltg.x = matrixportal.display.width - i
        # y descends from -16 (above screen) to 12 (runway level)
        ltg.y = -16 + (i * 28 // steps)
        wfeed(); time.sleep(_plane_speed_delay)
        if ltg.x < -40 or ltg.y > 14: break
    matrixportal.display.root_group = g
    gc.collect()

# ---- Labels ----
label1 = adafruit_display_text.label.Label(FONT,color=ROW_ONE_COLOUR,text="")
label1.x=1; label1.y=4
label2 = adafruit_display_text.label.Label(FONT,color=ROW_TWO_COLOUR,text="")
label2.x=1; label2.y=15
label3 = adafruit_display_text.label.Label(FONT,color=ROW_THREE_COLOUR,text="")
label3.x=1; label3.y=27

g = displayio.Group()
g.append(label1); g.append(label2); g.append(label3)
matrixportal.display.root_group = g

label1_short=label1_long=label2_short=label2_long=label3_short=label3_long=''

def flap_in(label, target):
    target = target.upper()
    steps = [FLAP_CHARS.index(ch) if ch in FLAP_CHARS else 0 for ch in target]
    mx = max(steps) if steps else 0
    for step in range(mx+1):
        label.text = ''.join(FLAP_CHARS[min(step,s)] for s in steps)
        wfeed(); time.sleep(FLAP_SPEED)
    label.text = target

def scroll(line, restore_x):
    line.x = matrixportal.display.width
    for i in range(matrixportal.display.width+1, 0-line.bounding_box[2], -1):
        line.x=i; wfeed(); time.sleep(TEXT_SPEED)
    line.x = restore_x

def flap_all(t1, t2, t3):
    """Flap all three rows simultaneously"""
    t1 = t1.upper(); t2 = t2.upper(); t3 = t3.upper()
    s1 = [FLAP_CHARS.index(c) if c in FLAP_CHARS else 0 for c in t1]
    s2 = [FLAP_CHARS.index(c) if c in FLAP_CHARS else 0 for c in t2]
    s3 = [FLAP_CHARS.index(c) if c in FLAP_CHARS else 0 for c in t3]
    mx = max(max(s1) if s1 else 0, max(s2) if s2 else 0, max(s3) if s3 else 0)
    for step in range(mx+1):
        label1.text = ''.join(FLAP_CHARS[min(step,s)] for s in s1)
        label2.text = ''.join(FLAP_CHARS[min(step,s)] for s in s2)
        label3.text = ''.join(FLAP_CHARS[min(step,s)] for s in s3)
        wfeed(); time.sleep(FLAP_SPEED)
    label1.text=t1; label2.text=t2; label3.text=t3

def display_flight():
    matrixportal.display.root_group = g
    label1.x=1; label2.x=1; label3.x=1
    # All three rows flap in simultaneously
    flap_all(label1_short, label2_short, label3_short)
    time.sleep(1)
    # Then scroll each long version in sequence
    label1.text=label1_long; scroll(label1,1); label1.text=label1_short; label1.x=1
    time.sleep(0.5)
    label2.text=label2_long; scroll(label2,1); label2.text=label2_short; label2.x=1
    time.sleep(0.5)
    label3.text=label3_long; scroll(label3,1); label3.text=label3_short; label3.x=1

def clear_flight():
    label1.text=label2.text=label3.text=""

def set_labels_from_feed(flight_info):
    global label1_short,label1_long,label2_short,label2_long,label3_short,label3_long
    callsign    = flight_info[13] or flight_info[16] or ''
    aircraft    = flight_info[8]  or ''
    origin      = flight_info[11] or ''
    destination = flight_info[12] or ''
    airline_icao= flight_info[18] if len(flight_info)>18 else ''
    speed_knots = flight_info[5]  if len(flight_info)>5  else 0

    setup_plane(aircraft, speed_knots, airline_icao)

    if aircraft.upper() in GA_TYPES:
        label1.color = GA_COLOUR
    elif airline_icao in AIRLINE_INFO:
        _,label1.color = AIRLINE_INFO[airline_icao]
    else:
        label1.color = COMMERCIAL_COLOUR

    label2.color = ROW_TWO_COLOUR
    label3.color = ROW_THREE_COLOUR

    # Enrich only what's actually missing - each API call costs ~1-2s
    hex_code = flight_info[0] if flight_info else ""
    adsb = {}
    needs_enrichment = hex_code and (not origin or not destination or not callsign)
    needs_operator   = hex_code and airline_icao not in AIRLINE_INFO

    if needs_enrichment:
        # adsb.lol - best single source, gets route + operator
        adsb = enrich_from_adsb(hex_code, requests_session)
        gc.collect()

    if needs_operator and not adsb.get("operator"):
        # Only hit planespotters if airline truly unknown (private jets etc)
        ps_op, ps_reg, _ = lookup_planespotters(hex_code, requests_session)
        if ps_op: adsb["operator"] = ps_op
        if ps_reg and not callsign: callsign = ps_reg
        gc.collect()

    # Fill gaps from ADS-B data
    if not origin and adsb.get("origin"):      origin      = adsb["origin"]
    if not destination and adsb.get("dest"):   destination = adsb["dest"]
    if not callsign and adsb.get("flight"):    callsign    = adsb["flight"]
    if not aircraft and adsb.get("aircraft"):  aircraft    = adsb["aircraft"]
    if not speed_knots and adsb.get("speed"):  speed_knots = int(adsb["speed"])

    if airline_icao in AIRLINE_INFO:
        airline_name = AIRLINE_INFO[airline_icao][0]
    elif adsb.get("operator"):
        airline_name = adsb["operator"][:12]
    else:
        airline_name = airline_icao
    orig_name,_  = AIRPORT_INFO.get(origin,(origin,''))
    dest_name,_  = AIRPORT_INFO.get(destination,(destination,''))
    aircraft_full= AIRCRAFT_NAMES.get(aircraft, aircraft)

    label1_short = callsign
    label1_long  = airline_name if airline_name != airline_icao else callsign
    label2_short = origin+'-'+destination if origin and destination else origin or destination
    label2_long  = orig_name+' - '+dest_name if orig_name and dest_name else orig_name or dest_name
    label3_short = aircraft
    label3_long  = aircraft_full
    print("Labels: "+callsign+" "+airline_name+" | "+origin+"-"+destination+" | "+aircraft_full+" | "+str(speed_knots)+"kt")

# ---- Weather ----
def temp_colour(temp):
    if TEMP_UNIT == "F":
        if temp <= 32: return 0x0044FF
        if temp <= 50: return 0x00CCFF
        if temp <= 68: return 0x00FF88
        if temp <= 82: return 0xFFCC00
        return 0xFF2200
    else:
        if temp <= 0: return 0x0044FF
        if temp <= 10: return 0x00CCFF
        if temp <= 20: return 0x00FF88
        if temp <= 28: return 0xFFCC00
        return 0xFF2200

def is_daytime(sunrise_str, sunset_str, current_time_str):
    """Compare HH:MM strings"""
    try:
        def to_mins(s):
            parts = s.split('T')[-1][:5].split(':')
            return int(parts[0])*60+int(parts[1])
        cur = to_mins(current_time_str)
        rise = to_mins(sunrise_str)
        sset = to_mins(sunset_str)
        return rise <= cur <= sset
    except:
        return True  # assume day if parse fails

def show_weather():
    try:
        resp = requests_session.get(WEATHER_URL)
        if resp.status_code==200:
            data = resp.json()
            cw   = data["current_weather"]
            temp = int(cw["temperature"])
            code = int(cw["weathercode"])
            wind = int(cw["windspeed"])
            ctime = cw.get("time","")
            cond = WEATHER_CODES.get(code,'Unknown')

            # Sunrise/sunset
            daily = data.get("daily",{})
            sunrise = daily.get("sunrise",[""])[0]
            sunset  = daily.get("sunset",[""])[0]
            day = is_daytime(sunrise, sunset, ctime)
            # After midday show sunset, before midday show sunrise
            try:
                cur_mins = int(ctime.split('T')[-1][:2])*60 + int(ctime.split('T')[-1][3:5])
                show_sunset = cur_mins >= 720
            except:
                show_sunset = not day

            # Sun/moon icon
            rise_str = sunrise.split('T')[-1][:5] if sunrise else ""
            sset_str = sunset.split('T')[-1][:5]  if sunset  else ""

            wg = displayio.Group()
            wl1 = adafruit_display_text.label.Label(FONT, color=temp_colour(temp), text=HOME_AIRPORT+" "+str(temp)+TEMP_UNIT)
            wl1.x=1; wl1.y=4
            wl2 = adafruit_display_text.label.Label(FONT,color=0xFFFFFF,text=cond[:10])
            wl2.x=1; wl2.y=15
            wl3 = adafruit_display_text.label.Label(FONT,color=0xFFAA00,
                text=("SET "+sset_str if show_sunset else "Up "+rise_str))
            wl3.x=1; wl3.y=26
            wg.append(wl1); wg.append(wl2); wg.append(wl3)
            matrixportal.display.root_group = wg
            print("Weather: "+str(temp)+TEMP_UNIT+" "+cond)
            for _ in range(12): wfeed(); time.sleep(0.5)
            matrixportal.display.root_group = g
    except Exception as e:
        print("Weather error:", e)
    gc.collect()

def show_weather_persistent(duration=20):
    try:
        resp = requests_session.get(WEATHER_URL)
        if resp.status_code != 200:
            time.sleep(duration)
            return
        data = resp.json()
        cw   = data["current_weather"]
        temp = int(cw["temperature"])
        code = int(cw["weathercode"])
        ctime = cw.get("time","")
        cond = WEATHER_CODES.get(code,'Unknown')

        daily = data.get("daily",{})
        sunrise = daily.get("sunrise",[""])[0]
        sunset  = daily.get("sunset",[""])[0]
        try:
            cur_mins = int(ctime.split('T')[-1][:2])*60 + int(ctime.split('T')[-1][3:5])
            show_sunset = cur_mins >= 720
        except:
            show_sunset = True
        rise_str = sunrise.split('T')[-1][:5] if sunrise else ""
        sset_str = sunset.split('T')[-1][:5]  if sunset  else ""

        wg = displayio.Group()
        wl1 = adafruit_display_text.label.Label(FONT, color=temp_colour(temp), text=HOME_AIRPORT+" "+str(temp)+TEMP_UNIT)
        wl1.x=1; wl1.y=4
        wl2 = adafruit_display_text.label.Label(FONT, color=0xFFFFFF, text=cond[:10])
        wl2.x=1; wl2.y=15
        wl3 = adafruit_display_text.label.Label(FONT, color=0xFFAA00,
            text=("SET "+sset_str if show_sunset else "Up "+rise_str))
        wl3.x=1; wl3.y=26
        scan_bmp = displayio.Bitmap(64, 1, 2)
        scan_pal = displayio.Palette(2)
        scan_pal[0] = 0x000000
        scan_pal[1] = 0x004400
        scan_tg = displayio.TileGrid(scan_bmp, pixel_shader=scan_pal, x=0, y=31)
        wg.append(wl1); wg.append(wl2); wg.append(wl3); wg.append(scan_tg)
        matrixportal.display.root_group = wg
        print("Weather (persistent): "+str(temp)+TEMP_UNIT+" "+cond)

        start = time.monotonic()
        while time.monotonic() - start < duration:
            elapsed = time.monotonic() - start
            pos = int((elapsed % 5.0) / 5.0 * 64)
            for x in range(64):
                scan_bmp[x, 0] = 1 if pos <= x < pos + 8 else 0
            wfeed()
            time.sleep(0.05)
    except Exception as e:
        print("Weather persistent error:", e)
    gc.collect()


def distance_km(lat, lon):
    dlat = (lat - MY_LAT) * 111.0
    dlon = (lon - MY_LON) * 111.0 * math.cos(MY_LAT * 3.14159 / 180)
    return math.sqrt(dlat*dlat + dlon*dlon)


def position_check(lat, lon):
    if not FILTER_DIRECTION:
        return True
    mid = (HEADING_MIN + HEADING_MAX) / 2
    if 45 <= mid < 135:   return lon < MY_LON   # eastbound, west of you
    if 135 <= mid < 225:  return lat > MY_LAT   # southbound, north of you
    if 225 <= mid < 315:  return lon > MY_LON   # westbound, east of you
    return lat < MY_LAT                          # northbound, south of you


def get_flights(url, headers):
    try:
        resp = requests_session.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            flights = []; raw = {}
            for fid, fi in data.items():
                if fid not in ("version", "full_count") and len(fi) > 13:
                    p = parse_fr24_row(fid, fi)
                    o = p["origin"]; d = p["dest"]
                    alt     = p["alt"]
                    heading = p["heading"]
                    lat     = p["lat"]
                    lon     = p["lon"]
                    heading_match = (not FILTER_DIRECTION or (HEADING_MIN <= heading <= HEADING_MAX))
                    alt_match = MIN_ALTITUDE <= alt <= MAX_ALTITUDE
                    if heading_match and alt_match and position_check(lat, lon):
                        callsign = p["callsign"]
                        aircraft = p["aircraft"]
                        if not SHOW_HELICOPTERS and aircraft.upper() in HELI_TYPES:
                            print(f"  heli skip {callsign} ({aircraft})")
                            continue
                        dist = distance_km(lat, lon)
                        flights.append((fid, o, d, dist, alt))
                        raw[fid] = fi
                        print(f"  MATCH {callsign} ({aircraft}) {o}->{d} alt:{alt}ft hdg:{heading} dist:{round(dist,1)}km")
                    else:
                        print(f"  skip {fid} alt:{alt} hdg:{heading}")
            flights.sort(key=lambda x: x[3])
            if flights:
                print(f"--- {len(flights)} matched, closest first ---")
                for i,(fid,o,d,dist,alt) in enumerate(flights):
                    fi = raw[fid]
                    callsign = fi[13] or fi[16] or fid
                    aircraft = fi[8] or '?'
                    print(f"  #{i+1} {callsign} ({aircraft}) {o}->{d} {round(dist,1)}km {alt}ft")
            else:
                print("  no matches")
            return flights, raw
        print("Flight API error:", resp.status_code)
        return [], {}
    except Exception as e:
        print("Flight error:", e); return [], {}


def show_flight_queue(flights, raw, classes=None):
    if not flights:
        return
    classes = classes or {}

    matrixportal.display.root_group = g

    planes = []
    for i, (fid, o, d, dist, alt) in enumerate(flights[:5]):
        fi = raw.get(fid)
        if not fi:
            continue
        callsign = fi[13] or fi[16] or fid
        aircraft = fi[8] or '?'
        aircraft_full = AIRCRAFT_NAMES.get(aircraft, aircraft) if SHOW_FULL_AIRCRAFT else aircraft
        cls = classes.get(fid, "unknown")
        o2, d2 = resolve_route(o, d, cls, HOME_AIRPORT)
        route = (o2 or "?") + "->" + (d2 or "?")
        planes.append((i+1, callsign, aircraft, aircraft_full, route, round(dist,1), alt))

    if not planes:
        return

    ROW_COLOURS = [
        0xFFFFFF, 0xFFFF00, 0xFF6600, 0xFF00FF, 0x00AAFF,
        0xFF9999, 0x00FFAA, 0xAA00FF,
    ]

    BAR_Y = 31
    bar_bmp = displayio.Bitmap(64, 1, 2)
    bar_pal = displayio.Palette(2)
    bar_pal[0] = 0x000000
    bar_pal[1] = 0x004400
    bar_tg = displayio.TileGrid(bar_bmp, pixel_shader=bar_pal, x=0, y=BAR_Y)
    g.append(bar_tg)

    total_ticks = QUERY_DELAY * 2
    tick = 0
    PLANE_HOLD = 4.0

    # Display each plane in turn, with a progress bar and scrolling text if needed
    try:
        while True:
            for idx, (pos, callsign, aircraft, aircraft_full, route, dist, alt) in enumerate(planes):
                colour = ROW_COLOURS[idx % len(ROW_COLOURS)]
                label1.color = colour
                label2.color = colour
                label3.color = colour
                label1.text = "#"+str(pos)+" "+callsign[:7]
                label1.x = 1
                label2.text = aircraft+" "+str(dist)+"km"
                label2.x = 1
                label3.text = route+" "+str(alt)+"ft"
                label3.x = 1

                plane_start = time.monotonic()
                scroll_done = False

                while True:
                    now = time.monotonic()
                    elapsed = now - plane_start

                    if elapsed >= 1.5 and not scroll_done:
                        scroll_done = True
                        text_width2 = label2.bounding_box[2]
                        text_width3 = label3.bounding_box[2]
                        needs_scroll2 = text_width2 > matrixportal.display.width
                        needs_scroll3 = text_width3 > matrixportal.display.width

                        if needs_scroll2 or needs_scroll3 or SHOW_FULL_AIRCRAFT:
                            if SHOW_FULL_AIRCRAFT:
                                label2.text = aircraft_full+" "+str(dist)+"km"
                                text_width2 = label2.bounding_box[2]
                                needs_scroll2 = text_width2 > matrixportal.display.width
                            scroll_end_x2 = -(text_width2 - matrixportal.display.width) - 2 if needs_scroll2 else 1
                            scroll_end_x3 = -(text_width3 - matrixportal.display.width) - 2 if needs_scroll3 else 1
                            sx2 = 1; sx3 = 1
                            scroll_start = time.monotonic()

                            while sx2 > scroll_end_x2 or sx3 > scroll_end_x3:
                                if sx2 > scroll_end_x2:
                                    sx2 -= 1
                                    label2.x = sx2
                                if sx3 > scroll_end_x3:
                                    sx3 -= 1
                                    label3.x = sx3
                                se = time.monotonic() - scroll_start
                                current_tick = min(tick + se / 0.5, total_ticks)
                                pixels_remaining = max(0, min(64, 64 - int((current_tick / total_ticks) * 64)))
                                for x in range(64):
                                    bar_bmp[x, 0] = 1 if x < pixels_remaining else 0
                                wfeed()
                                time.sleep(TEXT_SPEED)

                            se = time.monotonic() - scroll_start
                            tick += int(se / 0.5)
                            tick = min(tick, total_ticks)

                    pixels_remaining = max(0, min(64, 64 - int((tick / total_ticks) * 64)))
                    for x in range(64):
                        bar_bmp[x, 0] = 1 if x < pixels_remaining else 0
                    wfeed()
                    time.sleep(0.5)
                    tick += 1
                    if tick >= total_ticks:
                        return
                    if time.monotonic() - plane_start >= PLANE_HOLD:
                        break
    finally:
        g.remove(bar_tg)
        label1.text = ""
        label2.text = ""
        label3.text = ""
        label1.color = ROW_ONE_COLOUR
        label2.color = ROW_TWO_COLOUR
        label3.color = ROW_THREE_COLOUR

last_flight=''
last_mode=None

while True:
    checkConnection()
    wfeed()
    print("memory free: "+str(gc.mem_free())) # type: ignore

    if ENABLE_FLIGHTS:
        flights,raw = get_flights_demo(FLIGHT_URL, rheaders) if DEMO_MODE else get_flights(FLIGHT_URL, rheaders) # type: ignore 

        # Classify each flight, then apply the arrival/departure toggles
        classes = {}
        kept = []
        for f in flights:
            fid = f[0]; fi = raw[fid]
            cls = classify_flight(fi[11], fi[12], fi[3], HOME_AIRPORT,
                                  ARRIVAL_HEADING, HEADING_TOLERANCE)
            if not passes_direction_filter(cls, SHOW_ARRIVALS, SHOW_DEPARTURES):
                continue
            classes[fid] = cls
            kept.append(f)
        flights = kept

        if flights:
            mode = queue_mode([classes[f[0]] for f in flights])
            # Runway intro once per homogeneous corridor, and only when the
            # mode changes so a steady stream doesn't replay it every cycle.
            if mode != last_mode:
                if mode == "arrivals":
                    plane_animation_landing()
                elif mode == "departures":
                    plane_animation_take_off()
            last_mode = mode

            show_flight_queue(flights, raw, classes)
            if ENABLE_WEATHER:
                show_weather()
        else:
            last_mode = None
            if ENABLE_WEATHER:
                show_weather_persistent()
    elif ENABLE_WEATHER:
        show_weather_persistent()

    gc.collect()
    time.sleep(0.5)