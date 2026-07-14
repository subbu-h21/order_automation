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

# Real-world vendor accounts, as the CRM's Saved PO / reorder system knows
# them. Used only to fetch reorder suggestions and build the curated product
# list - the CRM has no concept of A.K.PHARMA's two Retailio distributor
# accounts below, it's one vendor relationship to the pharmacy.
CRM_SUPPLIERS = ["DRK ENTERPRISES", "A.K.PHARMA", "MAHAVEER MEDI-SALES PVT.LTD."]

# Retailio distributor tabs to search/allocate against, in priority order
# (highest discount first). A.K.PHARMA is split into its two Retailio
# distributor accounts (Outstation / Davangere): Retailio surfaces them as
# separate catalogs with independent stock and hidden per-order limits, so
# treating them as one combined tab (the old behavior) caused the same
# product to show up twice under near-identical names with no way to fall
# back from one to the other when one hit a hidden quantity cap.
SUPPLIERS = [
    "DRK ENTERPRISES",
    "A.K.PHARMA (OUTSTATION)",
    "A.K.PHARMA (DAVANGERE)",
    "MAHAVEER MEDI-SALES PVT.LTD.",
]

# Each entry maps to the distributor row name(s) to tick on Retailio's
# distributor-picker page for its dedicated tab.
SUPPLIER_DISTRIBUTOR_NAMES = {
    "DRK ENTERPRISES": ["Drk Enterprises"],
    "A.K.PHARMA (OUTSTATION)": ["A K Pharma - Outstation"],
    "A.K.PHARMA (DAVANGERE)": ["A K Pharma, Davangere"],
    "MAHAVEER MEDI-SALES PVT.LTD.": ["Mahaveer Medi Sales"],
}

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
