import streamlit as st
import pandas as pd
import json
from pathlib import Path
from _page_descriptions import render_page_description

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(page_title="🏢 Company Coverage Mapper", layout="wide")
st.title("🏢 Company Coverage Mapper")
render_page_description(__file__)
st.caption("Compare ESG master list vs News dataset coverage")

# =========================
# PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]

NEWS_PATH = BASE_DIR / "data" / "news_dataset.json"
ESG_PATH  = BASE_DIR / "data" / "esg_companies.json"

# =========================
# LOAD DATA
# =========================
def load_json(path: Path):
    if not path.exists():
        st.error(f"❌ Missing file: {path}")
        st.stop()

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


news_raw = load_json(NEWS_PATH)
esg_raw  = load_json(ESG_PATH)

news_df = pd.DataFrame(news_raw)
esg_df  = pd.DataFrame(esg_raw)

# Safety checks
required_news_cols = {"company_code"}
required_esg_cols  = {"code", "company_name"}

if not required_news_cols.issubset(news_df.columns):
    st.error(f"❌ news_dataset.json must contain columns: {required_news_cols}")
    st.stop()

if not required_esg_cols.issubset(esg_df.columns):
    st.error(f"❌ esg_companies.json must contain columns: {required_esg_cols}")
    st.stop()

# Normalize codes
news_df["company_code"] = news_df["company_code"].astype(str).str.upper().str.strip()
esg_df["code"] = esg_df["code"].astype(str).str.upper().str.strip()

# =========================
# EXTRACT COMPANY SETS
# =========================
news_codes = set(news_df["company_code"].dropna().unique())
esg_codes  = set(esg_df["code"].dropna().unique())

matched = sorted(news_codes & esg_codes)
missing_in_news = sorted(esg_codes - news_codes)
extra_in_news   = sorted(news_codes - esg_codes)

# =========================
# METRICS
# =========================
c1, c2, c3, c4 = st.columns(4)

c1.metric("ESG Companies", len(esg_codes))
c2.metric("Companies in News", len(news_codes))
c3.metric("Matched", len(matched))
c4.metric("Missing in News", len(missing_in_news))

st.divider()

# =========================
# COMPANY DISTRIBUTION
# =========================
st.subheader("📊 Company Distribution in News")

company_counts = (
    news_df["company_code"]
    .value_counts()
    .sort_index()
)
st.bar_chart(
    company_counts.rename("Number of Articles").to_frame(),
    use_container_width=True,
)

# =========================
# MATCHED COMPANIES
# =========================
st.subheader("✅ Companies Covered in News")

matched_df = (
    esg_df[esg_df["code"].isin(matched)]
    .sort_values("code")
    .reset_index(drop=True)
)

st.dataframe(matched_df, use_container_width=True)

# =========================
# MISSING ESG COMPANIES
# =========================
st.subheader("❌ ESG Companies Missing in News")

missing_df = (
    esg_df[esg_df["code"].isin(missing_in_news)]
    .sort_values("code")
    .reset_index(drop=True)
)

st.dataframe(missing_df, use_container_width=True)

# =========================
# EXTRA COMPANIES IN NEWS
# =========================
st.subheader("⚠️ Companies Appearing in News but Not in ESG List")

extra_df = pd.DataFrame(
    sorted(extra_in_news),
    columns=["company_code"]
)

st.dataframe(extra_df, use_container_width=True)

# =========================
# OPTIONAL: RAW CODE SETS
# =========================
with st.expander("🔍 Debug — Raw Code Sets"):
    st.write("News codes:", sorted(news_codes))
    st.write("ESG codes:", sorted(esg_codes))


# import streamlit as st
# import pandas as pd
# import json
# from pathlib import Path
# import matplotlib.pyplot as plt

# # =========================
# # PAGE CONFIG
# # =========================
# st.set_page_config(page_title="🏢 Company Coverage Mapper", layout="wide")
# st.title("🏢 Company Coverage Mapper")
# st.caption("Compare ESG master list vs News dataset coverage")

# # =========================
# # PATHS
# # =========================
# BASE_DIR = Path(__file__).resolve().parents[1]
# NEWS_PATH = BASE_DIR / "data" / "news_dataset.json"

# # =========================
# # ESG MASTER LIST (PASTE OR LOAD)
# # =========================
# ESG_COMPANIES = [
#     {"rank":1,"code":"PGEO","company_name":"PT Pertamina Geothermal Energy Tbk"},
#     {"rank":2,"code":"MPMX","company_name":"PT Mitra Pinasthika Mustika Tbk"},
#     {"rank":3,"code":"BMRI","company_name":"PT Bank Mandiri (Persero) Tbk"},
#     {"rank":4,"code":"JSMR","company_name":"PT Jasa Marga Tbk"},
#     {"rank":5,"code":"EMTK","company_name":"PT Elang Mahkota Teknologi Tbk"},
#     {"rank":6,"code":"SCMA","company_name":"PT Surya Citra Media Tbk"},
#     {"rank":7,"code":"TPIA","company_name":"PT Chandra Asri Pacific Tbk"},
#     {"rank":8,"code":"ERAA","company_name":"PT Erajaya Swasembada Tbk"},
#     {"rank":9,"code":"MNCN","company_name":"PT Media Nusantara Citra Tbk"},
#     {"rank":10,"code":"UNVR","company_name":"PT Unilever Indonesia Tbk"},
#     {"rank":11,"code":"BMTR","company_name":"PT Global Mediacom Tbk"},
#     {"rank":12,"code":"MTEL","company_name":"PT Dayamitra Telekomunikasi Tbk"},
#     {"rank":13,"code":"BBRI","company_name":"PT Bank Rakyat Indonesia (Persero) Tbk"},
#     {"rank":14,"code":"PWON","company_name":"PT Pakuwon Jati Tbk"},
#     {"rank":15,"code":"MAPA","company_name":"PT Map Aktif Adiperkasa Tbk"},
#     {"rank":16,"code":"ACES","company_name":"PT Aspirasi Hidup Indonesia Tbk"},
#     {"rank":17,"code":"AKRA","company_name":"PT AKR Corporindo Tbk"},
#     {"rank":18,"code":"AVIA","company_name":"PT Avia Avian Tbk"},
#     {"rank":19,"code":"BBNI","company_name":"PT Bank Negara Indonesia (Persero) Tbk"},
#     {"rank":20,"code":"BBCA","company_name":"PT Bank Central Asia Tbk"},
#     {"rank":21,"code":"SIDO","company_name":"PT Industri Jamu Dan Farmasi Sido Muncul Tbk"},
#     {"rank":22,"code":"GOTO","company_name":"PT GoTo Gojek Tokopedia Tbk"},
#     {"rank":23,"code":"BSDE","company_name":"PT Bumi Serpong Damai Tbk"},
#     {"rank":24,"code":"BNGA","company_name":"PT Bank CIMB Niaga Tbk"},
#     {"rank":25,"code":"PGAS","company_name":"PT Perusahaan Gas Negara Tbk"},
#     {"rank":26,"code":"MAPI","company_name":"PT Mitra Adiperkasa Tbk"},
#     {"rank":27,"code":"CMRY","company_name":"PT Cisarua Mountain Dairy Tbk"},
#     {"rank":28,"code":"TBIG","company_name":"PT Tower Bersama Infrastructure Tbk"},
#     {"rank":29,"code":"CTRA","company_name":"PT Ciputra Development Tbk"},
#     {"rank":30,"code":"TOWR","company_name":"PT Sarana Menara Nusantara Tbk"},
#     {"rank":31,"code":"SMGR","company_name":"PT Semen Indonesia (Persero) Tbk"},
#     {"rank":32,"code":"BUKA","company_name":"PT Bukalapak.com Tbk"},
#     {"rank":33,"code":"EXCL","company_name":"PT XLSMART Telecom Sejahtera Tbk"},
#     {"rank":34,"code":"MIKA","company_name":"PT Mitra Keluarga Karyasehat Tbk"},
#     {"rank":35,"code":"TLKM","company_name":"PT Telkom Indonesia (Persero) Tbk"},
#     {"rank":36,"code":"AUTO","company_name":"PT Astra Otoparts Tbk"},
#     {"rank":37,"code":"BFIN","company_name":"PT BFI Finance Indonesia Tbk"},
#     {"rank":38,"code":"MDKA","company_name":"PT Merdeka Copper Gold Tbk"},
#     {"rank":39,"code":"INTP","company_name":"PT Indocement Tunggal Prakarsa Tbk"},
#     {"rank":40,"code":"SRTG","company_name":"PT Saratoga Investama Sedaya Tbk"},
#     {"rank":41,"code":"HMSP","company_name":"PT HM Sampoerna Tbk"},
#     {"rank":42,"code":"ENRG","company_name":"PT Energi Mega Persada Tbk"},
#     {"rank":43,"code":"NISP","company_name":"PT Bank OCBC NISP Tbk"},
#     {"rank":44,"code":"BBTN","company_name":"PT Bank Tabungan Negara (Persero) Tbk"},
#     {"rank":45,"code":"GJTL","company_name":"PT Gajah Tunggal Tbk"},
#     {"rank":46,"code":"BRIS","company_name":"PT Bank Syariah Indonesia Tbk"},
#     {"rank":47,"code":"SMRA","company_name":"PT Summarecon Agung Tbk"},
#     {"rank":48,"code":"HEAL","company_name":"PT Medikaloka Hermina Tbk"},
#     {"rank":49,"code":"BRPT","company_name":"PT Barito Pacific Tbk"},
#     {"rank":50,"code":"INKP","company_name":"PT Indah Kiat Pulp & Paper Tbk"},
#     {"rank":51,"code":"ISAT","company_name":"PT Indosat Tbk"},
#     {"rank":52,"code":"PNLF","company_name":"PT Panin Financial Tbk"},
#     {"rank":53,"code":"TKIM","company_name":"PT Pabrik Kertas Tjiwi Kimia Tbk"},
#     {"rank":54,"code":"INCO","company_name":"PT Vale Indonesia Tbk"},
#     {"rank":55,"code":"LSIP","company_name":"PT PP London Sumatra Indonesia Tbk"},
#     {"rank":56,"code":"MIDI","company_name":"PT Midi Utama Indonesia Tbk"},
#     {"rank":57,"code":"KLBF","company_name":"PT Kalbe Farma Tbk"},
#     {"rank":58,"code":"ITMG","company_name":"PT Indo Tambangraya Megah Tbk"},
#     {"rank":59,"code":"MYOR","company_name":"PT Mayora Indah Tbk"},
#     {"rank":60,"code":"BTPS","company_name":"PT Bank BTPN Syariah Tbk"},
#     {"rank":61,"code":"AMRT","company_name":"PT Sumber Alfaria Trijaya Tbk"},
#     {"rank":62,"code":"ICBP","company_name":"PT Indofood CBP Sukses Makmur Tbk"},
#     {"rank":63,"code":"ANTM","company_name":"PT Aneka Tambang Tbk"},
#     {"rank":64,"code":"INDF","company_name":"PT Indofood Sukses Makmur Tbk"},
#     {"rank":65,"code":"ARTO","company_name":"PT Bank Jago Tbk"},
#     {"rank":66,"code":"NCKL","company_name":"PT Trimegah Bangun Persada Tbk"},
#     {"rank":67,"code":"ASII","company_name":"PT Astra International Tbk"},
#     {"rank":68,"code":"MBMA","company_name":"PT Merdeka Battery Materials Tbk"},
#     {"rank":69,"code":"MEDC","company_name":"PT Medco Energi Internasional Tbk"},
#     {"rank":70,"code":"ELSA","company_name":"PT Elnusa Tbk"},
#     {"rank":71,"code":"TAPG","company_name":"PT Triputra Agro Persada Tbk"},
#     {"rank":72,"code":"INDY","company_name":"PT Indika Energy Tbk"},
#     {"rank":73,"code":"SSIA","company_name":"PT Surya Semesta Internusa Tbk"},
#     {"rank":74,"code":"PANI","company_name":"PT Pantai Indah Kapuk Dua Tbk"},
#     {"rank":75,"code":"ESSA","company_name":"PT ESSA Industries Indonesia Tbk"},
#     {"rank":76,"code":"UNTR","company_name":"PT United Tractors Tbk"},
#     {"rank":77,"code":"JPFA","company_name":"PT JAPFA Comfeed Indonesia Tbk"},
#     {"rank":78,"code":"AMMN","company_name":"PT Amman Mineral Internasional Tbk"},
#     {"rank":79,"code":"CPIN","company_name":"PT Charoen Pokphand Indonesia Tbk"},
#     {"rank":80,"code":"PTBA","company_name":"PT Bukit Asam Tbk"},
#     {"rank":81,"code":"GGRM","company_name":"PT Gudang Garam Tbk"},
#     {"rank":82,"code":"ADRO","company_name":"PT Alamtri Resources Indonesia Tbk"},
#     {"rank":83,"code":"BRMS","company_name":"PT Bumi Resources Minerals Tbk"},
#     {"rank":84,"code":"HRUM","company_name":"PT Harum Energy Tbk"},
#     {"rank":85,"code":"ADMR","company_name":"PT Alamtri Minerals Indonesia Tbk"},
# ]

# # =========================
# # LOAD DATA
# # =========================
# if not NEWS_PATH.exists():
#     st.error(f"❌ Missing news dataset: {NEWS_PATH}")
#     st.stop()

# with open(NEWS_PATH, "r", encoding="utf-8") as f:
#     news_raw = json.load(f)

# news_df = pd.DataFrame(news_raw)

# # =========================
# # EXTRACT COMPANY CODES
# # =========================
# news_codes = set(news_df["company_code"].dropna().unique())
# esg_df = pd.DataFrame(ESG_COMPANIES)
# esg_codes = set(esg_df["code"].unique())

# matched = sorted(news_codes & esg_codes)
# missing_in_news = sorted(esg_codes - news_codes)
# extra_in_news = sorted(news_codes - esg_codes)

# # =========================
# # METRICS
# # =========================
# c1, c2, c3, c4 = st.columns(4)
# c1.metric("ESG Companies", len(esg_codes))
# c2.metric("In News", len(news_codes))
# c3.metric("Matched", len(matched))
# c4.metric("Missing in News", len(missing_in_news))

# st.divider()

# # =========================
# # COMPANY DISTRIBUTION
# # =========================
# st.subheader("📊 Company Distribution in News")

# company_counts = (
#     news_df["company_code"]
#     .value_counts()
#     .sort_index()
# )

# fig, ax = plt.subplots(figsize=(10, 4))
# company_counts.plot(kind="bar", ax=ax)
# ax.set_xlabel("Company Code")
# ax.set_ylabel("Articles")
# ax.set_title("News Coverage per Company")
# st.pyplot(fig)

# # =========================
# # MATCHED
# # =========================
# st.subheader("✅ Companies Covered in News")

# matched_df = esg_df[esg_df["code"].isin(matched)].sort_values("code")
# st.dataframe(matched_df, use_container_width=True)

# # =========================
# # MISSING
# # =========================
# st.subheader("❌ ESG Companies Missing in News")

# missing_df = esg_df[esg_df["code"].isin(missing_in_news)].sort_values("code")
# st.dataframe(missing_df, use_container_width=True)

# # =========================
# # EXTRA
# # =========================
# st.subheader("⚠️ Companies Appearing in News but Not in ESG List")

# extra_df = pd.DataFrame(sorted(extra_in_news), columns=["company_code"])
# st.dataframe(extra_df, use_container_width=True)
