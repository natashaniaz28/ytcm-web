# Primary search terms:
# all terms in the list(s) have to occur in a video title.

PRIMARY_SEARCH_TERMS = [["eternity"], ["iiterniti"], ["이터니티"]]


# Secondary search terms:
# One of the terms in the list has to occur in a video title in addition to the primary search terms.
# Not applicable if list stays empty.

SECONDARY_SEARCH_TERMS = ["paradise", "파라다이스"]

SECONDARY_SEARCH_TERMS_JP = [
    "音楽", "サウンドトラック", "サントラ",        # ongaku, soundotorakku, santora
    "劇伴", "BGM", "メドレー",                  # gekiban (film/TV score), bījīemu, medorē (medley)
    "ピアノ", "オーケストラ",                    # piano, ōkesutora
    "交響組曲", "コンサート"                     # kōkyō kumikyoku (symphonic suite), konsāto
]


# Excluded terms:
# Terms included in this list will let the video go unprocessed.

EXCLUDED_TERMS = []

# Perform search for this year:

SEARCH_YEAR = 2021


# Page length (YouTube API constant, don't change):

MAX_RESULTS = 50


CACHING = False


API_KEY_FILE = "YOUTUBE.API"

# Filenames of several utility files and folders:
CACHE_FILE      = "channel_data_cache.json"
COMMENTS_FOLDER = "COMMENTS"

COMMENTS_JSON            = "Comments.json"
COMMENTS_ANONYMIZED_JSON = "Comments_anonymized.json"
ANONYMIZATION_MAP_JSON   = "Anonymization_map.json"
COMMENTS_HTML            = "Comments.html"
COMMENTS_GEXF_ON         = "Comments+replies.gexf"
COMMENTS_GEXF_OFF        = "Comments.gexf"
COMMENTS_CSV             = "Comments.csv"
FILTER_JSON              = "Filtered.json"


VERSION_DATE = "2025-09-08"


##

TUBECONNECTSETTINGS = [
    ("Comments.json", "LoZ", "Legend of Zelda"),
    ("NinoKuni.json", "NnK", "Ni no Kuni"),
    ("Octopath.json", "OT", "Octopath Traveler")
]
