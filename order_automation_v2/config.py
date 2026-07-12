import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CHROME_PROFILE_DIR = os.environ["CHROME_PROFILE_DIR"]

CRM_URL = "https://shubhadahealth.com:7007/"
ORDER_SITE_URL = "https://retailio.in/"

BRANCHES = {
    "HOSPET ROAD": {
        "username": os.environ["CRM_USERNAME"],
        "password": os.environ["CRM_PASSWORD"],
    },
    "SHIVAJI CHOWK": {
        "username": os.environ["CRM_USERNAME_SHIVAJI_CHOWK"],
        "password": os.environ["CRM_PASSWORD_SHIVAJI_CHOWK"],
    },
}
DEFAULT_BRANCH = "HOSPET ROAD"

SUPPLIERS = ["DRK ENTERPRISES", "A.K.PHARMA", "MAHAVEER MEDI-SALES PVT.LTD."]

# Priority order == order of SUPPLIERS above (highest discount first).
# Each supplier maps to the distributor row name(s) to tick on Retailio's
# distributor-picker page for its dedicated tab.
SUPPLIER_DISTRIBUTOR_NAMES = {
    "DRK ENTERPRISES": ["Drk Enterprises"],
    "A.K.PHARMA": ["A K Pharma - Outstation", "A K Pharma, Davangere"],
    "MAHAVEER MEDI-SALES PVT.LTD.": ["Mahaveer Medi Sales"],
}

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
