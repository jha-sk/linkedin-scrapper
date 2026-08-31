import json

from bs4 import BeautifulSoup

from phantom.scraper import voyager

PAGE = """
<html><body>
<code id="bpr-guid-1">%s</code>
<code id="bpr-guid-2">not json at all</code>
</body></html>
""" % json.dumps(
    {
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                "entityUrn": "urn:li:fsd_profile:ACoAADe92ckBElZ",
                "objectUrn": "urn:li:member:935188937",
                "publicIdentifier": "sk-jha",
                "firstName": "Sourabh",
                "lastName": "Jha",
                "headline": "AI / LLM Application Engineer",
                "geoLocation": {"defaultLocalizedName": "Gurugram, Haryana, India"},
                "profilePicture": {
                    "displayImageReference": {
                        "vectorImage": {
                            "rootUrl": "https://media.example.com/img/",
                            "artifacts": [
                                {"width": 100, "fileIdentifyingUrlPathSegment": "small.jpg"},
                                {"width": 400, "fileIdentifyingUrlPathSegment": "large.jpg"},
                            ],
                        }
                    },
                    "urn": "urn:li:digitalmediaAsset:D5603AQ",
                },
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Position",
                "title": "Associate Software Engineer",
                "companyName": "Accenture",
                "locationName": "Gurugram",
                "description": "Backend features on an enterprise platform.",
                "companyUrn": "urn:li:fsd_company:1033",
                "dateRange": {"start": {"month": 11, "year": 2024}},
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Position",
                "title": "Intern",
                "companyName": "Somewhere",
                "dateRange": {"start": {"year": 2023}, "end": {"month": 10, "year": 2024}},
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Education",
                "schoolName": "SRM University",
                "degreeName": "Bachelor of Technology - BTech",
                "fieldOfStudy": "Computer Science",
                "schoolUrn": "urn:li:fsd_school:srm-university-haryana",
                "dateRange": {"start": {"year": 2019}, "end": {"year": 2023}},
            },
            {"$type": "com.linkedin.voyager.dash.identity.profile.Skill", "name": "Kubernetes"},
            {"$type": "com.linkedin.voyager.dash.identity.profile.Skill", "name": "PostgreSQL"},
            {
                "$type": "com.linkedin.voyager.dash.organization.Company",
                "universalName": "accenture",
                "industry": {"localizedName": "Management Consulting"},
                "entityUrn": "urn:li:fsd_company:1033",
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.ProfileNetworkInfo",
                "followersCount": 610,
                "connectionsCount": 609,
                "distance": {"value": "OUT_OF_NETWORK"},
            },
        ]
    }
)


def parsed():
    return voyager.parse(BeautifulSoup(PAGE, "lxml"))


def test_identity_fields():
    out = parsed()
    assert out["linkedin_profile_slug"] == "sk-jha"
    assert out["first_name"] == "Sourabh"
    assert out["last_name"] == "Jha"
    assert out["linkedin_profile_id"] == "935188937"
    assert out["location"] == "Gurugram, Haryana, India"


def test_largest_profile_image_is_chosen():
    out = parsed()
    assert out["linkedin_profile_image_url"] == "https://media.example.com/img/large.jpg"
    assert out["linkedin_profile_image_urn"] == "urn:li:digitalmediaAsset:D5603AQ"


def test_current_position_wins_over_past_one():
    out = parsed()
    assert out["linkedin_job_title"] == "Associate Software Engineer"
    assert out["company_name"] == "Accenture"
    assert out["linkedin_job_date_range"] == "Nov 2024 - Present"


def test_education_and_skills():
    out = parsed()
    assert out["linkedin_school_name"] == "SRM University"
    assert out["linkedin_school_date_range"] == "2019 - 2023"
    assert out["linkedin_skills_label"] == "Kubernetes, PostgreSQL"


def test_network_info():
    out = parsed()
    assert out["linkedin_followers_count"] == 610
    assert out["linkedin_connections_count"] == 609
    assert out["connection_degree"] == "Out of Network"


def test_company_entity():
    out = parsed()
    assert out["linkedin_company_slug"] == "accenture"
    assert out["company_industry"] == "Management Consulting"


def test_page_without_a_model_store_yields_nothing():
    assert voyager.parse(BeautifulSoup("<html><body><p>hi</p></body></html>", "lxml")) == {}


def test_unparseable_blob_does_not_raise():
    html = '<html><body><code>{"included": [broken</code></body></html>'
    assert voyager.parse(BeautifulSoup(html, "lxml")) == {}
