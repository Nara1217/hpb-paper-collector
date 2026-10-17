"""네트워크 없이 돌아가는 테스트. 실제 API 응답 형식을 본뜬 가짜 데이터를 사용합니다.

실행: python -m pytest -q
"""
import json
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import yaml

from collector.filter import KeywordFilter
from collector.main import run
from collector.models import Paper
from collector.sources.biorxiv import PreprintSource, to_paper
from collector.sources.pubmed import parse_article
from collector.storage import LocalJSONStorage

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8"))

PUBMED_XML = """<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>41000001</PMID><Article>
<Journal><Title>Hepatology</Title></Journal>
<ArticleTitle>Single-cell atlas of <i>lenvatinib</i>-resistant hepatocellular carcinoma organoids</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Drug resistance limits HCC therapy.</AbstractText>
<AbstractText Label="METHODS">We used scRNA-seq of patient-derived organoids (PDOs) and PDX models.</AbstractText></Abstract>
<AuthorList><Author><LastName>Kim</LastName><ForeName>Jisoo</ForeName></Author><Author><CollectiveName>HCC Consortium</CollectiveName></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation>
<PubmedData><History><PubMedPubDate PubStatus="entrez"><Year>2026</Year><Month>10</Month><Day>15</Day></PubMedPubDate></History>
<ArticleIdList><ArticleId IdType="pubmed">41000001</ArticleId><ArticleId IdType="doi">10.1000/HEP.2026.1</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""

BIORXIV_ITEM = {
    "title": "Cancer-associated fibroblasts drive gemcitabine resistance in PDAC",
    "authors": "Lee, A.; Park, B.",
    "doi": "10.1101/2026.10.01.000001", "date": "2026-10-14", "version": "2",
    "category": "cancer biology",
    "abstract": "Using spatial transcriptomics (Visium) we map CAFs in the PDAC tumor microenvironment.",
    "published": "NA", "server": "bioRxiv",
}


def kf():
    return KeywordFilter.from_config(CFG)


def test_pubmed_parse_and_filter():
    art = ET.fromstring(PUBMED_XML).find("PubmedArticle")
    p = parse_article(art)
    assert p.id == "doi:10.1000/hep.2026.1"
    assert p.date == "2026-10-15"
    assert p.authors == ["Jisoo Kim", "HCC Consortium"]
    assert "lenvatinib" in p.title and "METHODS:" in p.abstract
    assert kf().apply(p)
    assert p.matched_cancer == ["HCC"]
    assert set(p.matched_topics) >= {"organoid", "single_cell", "drug_resistance"}


def test_biorxiv_parse_and_filter():
    p = to_paper(BIORXIV_ITEM, "biorxiv")
    assert p.is_preprint and p.version == "2" and p.published_doi is None
    assert p.url.endswith("v2")
    assert kf().apply(p)
    assert p.matched_cancer == ["pancreatic"]
    assert set(p.matched_topics) >= {"spatial", "tumor_microenvironment", "drug_resistance"}


def test_filter_rejects_and_abbreviation_rules():
    f = kf()
    off_topic = Paper(id="x", source="pubmed", title="Organoid model of colon cancer",
                      abstract="scRNA-seq of colorectal tumors", authors=[], date="", url="")
    assert not f.apply(off_topic)  # 주제는 맞지만 암종이 아님
    tamox = Paper(id="y", source="pubmed", title="Tamoxifen in HCC", abstract="hcc and tamoxifen",
                  authors=[], date="", url="")
    assert not f.apply(tamox)       # "TAM" 약어가 tamoxifen에 걸리면 안 됨
    tams = Paper(id="z", source="pubmed", title="TAMs in HCC", abstract="", authors=[], date="", url="")
    assert f.apply(tams) and "tumor_microenvironment" in tams.matched_topics


def test_preprint_keeps_latest_version(monkeypatch):
    src = PreprintSource("biorxiv", {})
    v1 = dict(BIORXIV_ITEM, version="1")
    monkeypatch.setattr(src, "fetch_raw", lambda s, e: [v1, BIORXIV_ITEM])
    out = src.collect(date(2026, 10, 14), date(2026, 10, 15))
    assert len(out) == 1 and out[0].version == "2"


def test_storage_dedup_and_classification(tmp_path):
    st = LocalJSONStorage(tmp_path)
    p = to_paper(BIORXIV_ITEM, "biorxiv")
    assert st.save_papers([p], "2026-10-15") == 1
    assert st.save_papers([p], "2026-10-16") == 0          # 다음 날 다시 걸려도 중복 저장 안 함
    assert [x.id for x in st.iter_papers(only_unclassified=True)] == [p.id]
    st.set_classification(p.id, {"by": "agent", "labels": ["CAF"]})
    assert list(LocalJSONStorage(tmp_path).iter_papers(only_unclassified=True)) == []
    line = (tmp_path / "papers/2026-10-15.jsonl").read_text().strip()
    assert json.loads(line)["classification"]["labels"] == ["CAF"]


def test_run_end_to_end_with_fake_sources(tmp_path, monkeypatch):
    class Fake:
        def __init__(self, name, papers):
            self.name, self.papers = name, papers

        def collect(self, *a):
            return self.papers

    pm = parse_article(ET.fromstring(PUBMED_XML).find("PubmedArticle"))
    bx = to_paper(BIORXIV_ITEM, "biorxiv")
    noise = Paper(id="doi:n", source="biorxiv", title="Sleep and CSF flow", abstract="", authors=[], date="", url="")
    failing = Fake("medrxiv", None)
    failing.collect = lambda *a: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setattr("collector.main.build_sources",
                        lambda cfg, s: [Fake("pubmed", [pm]), Fake("biorxiv", [bx, noise]), failing])
    st = LocalJSONStorage(tmp_path)
    rep = run(CFG, st, date(2026, 10, 14), date(2026, 10, 15))
    assert rep["saved"] == 2
    assert rep["sources"]["biorxiv"] == {"fetched": 2, "matched": 1, "new": 1}
    assert rep["errors"] and "medrxiv" in rep["errors"][0]
    assert list((tmp_path / "runs").glob("*.json"))
