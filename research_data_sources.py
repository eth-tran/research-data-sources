import pandas as pd
import requests
import time

# =========================
# SAFE SEC REQUEST
# =========================
def safe_sec_request(url, headers, sleep=0.2):
    """
    Safely request JSON from the SEC, respecting rate limits
    and handling non-JSON responses.
    """
    try:
        r = requests.get(url, headers=headers)
        time.sleep(sleep)  # REQUIRED to avoid SEC throttling

        if r.status_code != 200:
            print(f"Skipping {url} (status {r.status_code})")
            return None

        return r.json()

    except ValueError:
        print(f"Non-JSON response from {url}")
        return None
    except requests.RequestException as e:
        print(f"Request failed for {url}: {e}")
        return None


# =========================
# CONFIG
# =========================
HEADERS = {"User-Agent": "e8tran@uwaterloo.ca"}

# =========================
# GET COMPANY LIST
# =========================
url = "https://www.sec.gov/files/company_tickers.json"
data = requests.get(url, headers=HEADERS).json()

companies = (
    pd.DataFrame.from_dict(data, orient="index")
    .rename(columns={"cik_str": "CIK"})
)

companies["CIK"] = companies["CIK"].astype(str).str.zfill(10)
companies = companies[["CIK", "ticker", "title"]]

CIKS = companies["CIK"].head(50).tolist()

# =========================
# CIK --> TICKER MAP
# =========================
cik_map = companies[["CIK", "ticker"]].copy()

# =========================
# EDGAR FUNDAMENTALS
# =========================
all_fundamentals = []

REVENUE_TAGS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet"
]

def extract_metric(facts, tags, output_name):
    for tag in tags:
        df = pd.DataFrame(
            facts.get(tag, {}).get("units", {}).get("USD", [])
        )

        if df.empty:
            continue

        if "form" in df.columns:
            df = df[df["form"].isin(["10-K", "20-F"])]

        if "fy" in df.columns:
            df["year"] = df["fy"]
        elif "end" in df.columns:
            df["year"] = pd.to_datetime(df["end"]).dt.year
        else:
            continue

        if "filed" in df.columns:
            df = df.sort_values("filed")

        df = df.drop_duplicates(subset="year", keep="last")

        df = df[["year", "val"]]
        df.columns = ["year", output_name]

        return df

    return pd.DataFrame(columns=["year", output_name])


for cik in CIKS:
    print(f"Fetching EDGAR data for {cik}...")

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    data = safe_sec_request(url, HEADERS)

    if data is None or "facts" not in data:
        continue

    facts_root = data.get("facts", {})

    if "us-gaap" in facts_root:
        facts = facts_root["us-gaap"]
    elif "ifrs-full" in facts_root:
        facts = facts_root["ifrs-full"]
    else:
        continue

    revenue = extract_metric(facts, REVENUE_TAGS, "revenue")
    assets = extract_metric(facts, ["Assets"], "assets")

    if revenue.empty or assets.empty:
        continue

    df = revenue.merge(assets, on="year", how="inner")
    df["CIK"] = cik

    all_fundamentals.append(df)

fundamentals = pd.concat(all_fundamentals, ignore_index=True)

# =========================
# ADD TICKER
# =========================
fundamentals = fundamentals.merge(
    cik_map,
    on="CIK",
    how="left"
)

fundamentals.to_csv("fundamentals_edgar.csv", index=False)

# =========================
# FINAL DATASET
# =========================
final = fundamentals.sort_values(["CIK", "year"]).reset_index(drop=True)

final["asset_growth"] = final.groupby("CIK")["assets"].pct_change()

final.to_csv("financial_decision_dataset_multi_company.csv", index=False)

print("EDGAR multi-company dataset created")
