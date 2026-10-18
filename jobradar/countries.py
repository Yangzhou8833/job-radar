"""Country recognition for free-text job locations ("Hamburg Office", "Hybrid - Berlin",
"Amsterdam, North Holland, Netherlands").

Each supported country has a set of names and major cities. `country_of` checks the
countries in your profile's scope first (in the order you listed them, so "Hamburg or
Amsterdam" counts for whichever comes first), then every other known country, then a
list of far-away places. Anything unrecognised gets your profile's `unknown_location`.

To support a new country, add an entry to COUNTRIES. `iso` is the lowercase code
SmartRecruiters filters on; `workable` is the country name Workable reports.
"""
import re

COUNTRIES = {
    "DE": {
        "workable": "Germany", "iso": "de",
        "names": r"germany|deutschland|(?:^|,\s*)de\s*$|bayern|bavaria|hessen|\bnrw\b|nordrhein|baden-württemberg|niedersachsen|sachsen"
                 r"|schleswig|brandenburg|thüringen|rheinland|saarland|mecklenburg",
        "cities": r"berlin|hamburg|münchen|munich|muenchen|köln|koeln|cologne|frankfurt|stuttgart|düsseldorf|dusseldorf"
                  r"|duesseldorf|leipzig|dortmund|essen|bremen|dresden|hannover|hanover|nürnberg|nuremberg|duisburg|bochum"
                  r"|wuppertal|bielefeld|bonn|münster|karlsruhe|mannheim|augsburg|wiesbaden|aachen|braunschweig|kiel"
                  r"|chemnitz|halle|magdeburg|freiburg|krefeld|mainz|lübeck|erfurt|rostock|kassel|potsdam|saarbrücken"
                  r"|ludwigshafen|oldenburg|osnabrück|leverkusen|heidelberg|darmstadt|regensburg|ingolstadt|würzburg"
                  r"|wolfsburg|\bulm\b|heilbronn|göttingen|offenbach|fürth|erlangen|jena|paderborn|gütersloh|herzogenaurach"
                  r"|walldorf|eschborn|neuss|ratingen|garching|bad homburg|gilching",
    },
    "NL": {
        "workable": "Netherlands", "iso": "nl",
        "names": r"netherlands|nederland|holland|(?:^|,\s*)nl\s*$",
        "cities": r"amsterdam|rotterdam|utrecht|eindhoven|den haag|the hague|'s-gravenhage|groningen|leiden|delft|haarlem"
                  r"|amersfoort|arnhem|nijmegen|tilburg|breda|maastricht|zwolle|hertogenbosch|den bosch|hoofddorp|schiphol"
                  r"|almere|amstelveen|venlo|enschede|apeldoorn",
    },
    "AT": {
        "workable": "Austria", "iso": "at",
        "names": r"austria|österreich|oesterreich|(?:^|,\s*)at\s*$",
        "cities": r"vienna|wien|graz|linz|salzburg|innsbruck|klagenfurt|st\.? pölten|\bwels\b|dornbirn|villach|bregenz"
                  r"|wiener neustadt",
    },
    "PL": {
        "workable": "Poland", "iso": "pl",
        "names": r"poland|polska|(?:^|,\s*)pl\s*$",
        "cities": r"warsaw|warszawa|krak[oó]w|cracow|wroc[lł]aw|gda[nń]sk|pozna[nń]|[lł][oó]d[zź]|katowice|gdynia|szczecin"
                  r"|lublin|bydgoszcz|bia[lł]ystok|rzesz[oó]w",
    },
    "CH": {
        "workable": "Switzerland", "iso": "ch",
        "names": r"switzerland|schweiz|suisse|svizzera",
        "cities": r"zürich|zurich|geneva|genève|genf|basel|\bbern\b|lausanne|lucerne|luzern|zug|st\.? gallen|winterthur|lugano",
    },
    "BE": {
        "workable": "Belgium", "iso": "be",
        "names": r"belgium|belgique|belgië",
        "cities": r"brussels|bruxelles|brussel|antwerp|antwerpen|ghent|gent|leuven|liège|liege|bruges|brugge|mechelen",
    },
    "LU": {"workable": "Luxembourg", "iso": "lu", "names": r"luxembourg|luxemburg", "cities": r"esch-sur-alzette"},
    "FR": {
        "workable": "France", "iso": "fr",
        "names": r"france",
        "cities": r"paris|lyon|marseille|toulouse|nice|nantes|strasbourg|montpellier|bordeaux|lille|rennes|grenoble",
    },
    "UK": {
        "workable": "United Kingdom", "iso": "gb",
        "names": r"united kingdom|\buk\b|england|scotland|wales|great britain",
        "cities": r"london|manchester|edinburgh|belfast|cardiff|oxford|cambridge|winnersh|reading|bristol|leeds|birmingham"
                  r"|glasgow|liverpool|sheffield|newcastle|nottingham|southampton|brighton|swansea|aberdeen|milton keynes"
                  r"|guildford|slough|watford|leicester|coventry",
    },
    "IE": {"workable": "Ireland", "iso": "ie", "names": r"ireland", "cities": r"dublin|cork|galway|limerick"},
    "ES": {
        "workable": "Spain", "iso": "es",
        "names": r"spain|españa",
        "cities": r"madrid|barcelona|valencia|seville|sevilla|malaga|málaga|bilbao|zaragoza|palma",
    },
    "PT": {"workable": "Portugal", "iso": "pt", "names": r"portugal", "cities": r"lisbon|lisboa|porto|braga|coimbra"},
    "IT": {
        "workable": "Italy", "iso": "it",
        "names": r"italy|italia",
        "cities": r"milan|milano|rome|roma|turin|torino|bologna|florence|firenze|naples|napoli|verona|padova",
    },
    "DK": {"workable": "Denmark", "iso": "dk", "names": r"denmark|danmark", "cities": r"copenhagen|københavn|aarhus|odense|aalborg"},
    "SE": {"workable": "Sweden", "iso": "se", "names": r"sweden|sverige", "cities": r"stockholm|gothenburg|göteborg|malmö|malmo|uppsala"},
    "NO": {"workable": "Norway", "iso": "no", "names": r"norway|norge", "cities": r"oslo|bergen|trondheim|stavanger"},
    "FI": {"workable": "Finland", "iso": "fi", "names": r"finland|suomi", "cities": r"helsinki|espoo|tampere|turku|oulu"},
    "CZ": {"workable": "Czechia", "iso": "cz", "names": r"czech|czechia|česko", "cities": r"prague|praha|brno|ostrava"},
}

# Places outside every supported country. A match means "out of scope" (or an unsupported country).
FAR_AWAY = re.compile(
    r"greece|athens|romania|bucharest|bulgaria|sofia|hungary|budapest|serbia|belgrade|croatia|zagreb|ukraine|kyiv"
    r"|estonia|tallinn|latvia|riga|lithuania|vilnius|slovakia|bratislava|slovenia|ljubljana|cyprus|malta|iceland"
    r"|united states|\busa\b|\bus\b|\bu\.s\.|new york|nyc|san francisco|boston|chicago|seattle|austin|los angeles"
    r"|north america|americas|canada|toronto|vancouver|montreal|brazil|brasil|s[ãa]o paulo|rio de janeiro|mexico|m[ée]xico"
    r"|argentina|buenos aires|colombia|bogot[aá]|chile|santiago|peru|lima|latam|latin america"
    r"|india|bangalore|bengaluru|mumbai|delhi|hyderabad|pune|chennai|china|shanghai|beijing|shenzhen|hong kong"
    r"|singapore|dubai|\buae\b|abu dhabi|saudi|riyadh|qatar|doha|israel|tel aviv|turkey|t[üu]rkiye|istanbul"
    r"|egypt|cairo|nigeria|lagos|kenya|nairobi|south africa|cape town|johannesburg|australia|sydney|melbourne"
    r"|new zealand|japan|tokyo|korea|seoul|taiwan|taipei|philippines|manila|vietnam|indonesia|jakarta"
    r"|malaysia|kuala lumpur|thailand|bangkok|munich, (?:fl|tx)", re.I)

_RX = {code: re.compile(f"{c['names']}|{c['cities']}", re.I) for code, c in COUNTRIES.items()}


def country_of(location, scope, unknown="", strict=False):
    """Country code from `scope` for an in-scope location, None for anywhere else.

    Blank, "Remote" or an unrecognised town gets `unknown` (a code, or "" for out of
    scope). `strict` is used for global sources such as company career feeds, where only
    a positively recognised location counts."""
    loc = location or ""
    for code in scope:
        if _RX[code].search(loc):
            return code
    if any(rx.search(loc) for code, rx in _RX.items() if code not in scope) or FAR_AWAY.search(loc):
        return None
    if strict or not unknown or unknown not in scope:
        return None
    return unknown


def workable_name(code):
    return COUNTRIES[code]["workable"]


def iso(code):
    return COUNTRIES[code]["iso"]
