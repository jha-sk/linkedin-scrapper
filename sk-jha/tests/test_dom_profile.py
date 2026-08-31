from bs4 import BeautifulSoup

from phantom.scraper import dom_profile

PROFILE_HTML = """
<html><body><main>
  <section class="artdeco-card">
    <h1>Sourabh Jha</h1>
    <div class="text-body-medium break-words">
      <span aria-hidden="true">AI / LLM Application Engineer</span>
      <span class="visually-hidden">AI / LLM Application Engineer</span>
    </div>
    <span class="text-body-small inline t-black--light">
      <span aria-hidden="true">Gurugram, Haryana, India</span>
      <span class="visually-hidden">Gurugram, Haryana, India</span>
    </span>
    <p class="t-black--light">610 followers &middot; 609 connections</p>
    <img src="https://media.licdn.com/dms/image/v2/D5603AQ/profile.jpg">
  </section>

  <section>
    <div id="about"></div>
    <div class="display-flex full-width">
      <span aria-hidden="true">I build LLM-powered systems end to end, from the agent pipeline down to the deploy.</span>
    </div>
  </section>

  <section>
    <div id="experience"></div>
    <ul>
      <li>
        <a href="/company/accenture/"><span>Accenture</span></a>
        <div class="t-bold"><span aria-hidden="true">Associate Software Engineer</span></div>
        <span class="t-14 t-normal"><span aria-hidden="true">Accenture &middot; Full-time</span></span>
        <span class="t-14 t-black--light"><span aria-hidden="true">Nov 2024 - Present</span></span>
        <span class="t-14 t-black--light"><span aria-hidden="true">Gurugram</span></span>
      </li>
      <li>
        <div class="t-bold"><span aria-hidden="true">Intern</span></div>
        <span class="t-14 t-normal"><span aria-hidden="true">Somewhere</span></span>
      </li>
    </ul>
  </section>

  <section>
    <div id="education"></div>
    <ul>
      <li>
        <a href="/school/srm-university-haryana/"><span>SRM</span></a>
        <div class="t-bold"><span aria-hidden="true">SRM University Sonepat, Haryana</span></div>
        <span class="t-14 t-normal"><span aria-hidden="true">Bachelor of Technology - BTech, Computer Science</span></span>
        <span class="t-14 t-black--light"><span aria-hidden="true">Aug 2019 - Aug 2023</span></span>
      </li>
    </ul>
  </section>

  <section>
    <div id="skills"></div>
    <ul>
      <li><div class="t-bold"><span aria-hidden="true">Kubernetes</span></div></li>
      <li><div class="t-bold"><span aria-hidden="true">PostgreSQL</span></div></li>
    </ul>
  </section>
</main></body></html>
"""

AUTHWALL_HTML = """
<html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
  <h1>Join LinkedIn</h1>
  <p>Sign in to view more profiles</p>
</main></body></html>
"""

SHELL_HTML = "<html><head><title>Sourabh Jha | LinkedIn</title></head><body><main></main></body></html>"


def parsed():
    return dom_profile.parse(BeautifulSoup(PROFILE_HTML, "lxml"), "sk-jha")


def test_name_is_not_doubled_by_the_screen_reader_span():
    out = parsed()
    assert out["scraper_full_name"] == "Sourabh Jha"
    assert out["first_name"] == "Sourabh"
    assert out["last_name"] == "Jha"


def test_headline_and_location_read_the_visible_span_only():
    out = parsed()
    assert out["linkedin_headline"] == "AI / LLM Application Engineer"
    assert out["location"] == "Gurugram, Haryana, India"


def test_counts_are_parsed_from_the_top_card():
    out = parsed()
    assert out["linkedin_followers_count"] == 610
    assert out["linkedin_connections_count"] == 609


def test_current_role_is_the_first_experience_row():
    out = parsed()
    assert out["linkedin_job_title"] == "Associate Software Engineer"
    assert out["company_name"] == "Accenture"
    assert out["linkedin_job_date_range"] == "Nov 2024 - Present"
    assert out["linkedin_company_slug"] == "accenture"


def test_education_splits_degree_from_field_of_study():
    out = parsed()
    assert out["linkedin_school_name"] == "SRM University Sonepat, Haryana"
    assert out["linkedin_school_degree"] == "Bachelor of Technology - BTech"
    assert out["linkedin_school_field_of_study"] == "Computer Science"
    assert out["linkedin_school_company_slug"] == "srm-university-haryana"


def test_skills_are_joined():
    out = parsed()
    assert out["linkedin_skills_label"] == "Kubernetes, PostgreSQL"


def test_about_section_is_read():
    assert "LLM-powered systems" in parsed()["linkedin_description"]


def test_render_detection_accepts_a_real_profile():
    assert dom_profile.looks_rendered(BeautifulSoup(PROFILE_HTML, "lxml")) is True


def test_render_detection_rejects_the_authwall_despite_its_h1_and_title():
    assert dom_profile.looks_rendered(BeautifulSoup(AUTHWALL_HTML, "lxml")) is False


def test_render_detection_rejects_an_empty_shell():
    assert dom_profile.looks_rendered(BeautifulSoup(SHELL_HTML, "lxml")) is False


def test_missing_sections_do_not_raise():
    out = dom_profile.parse(BeautifulSoup(SHELL_HTML, "lxml"), "sk-jha")
    assert out["linkedin_profile_slug"] == "sk-jha"



CURRENT_HTML = """
<html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
  <section class="bdfe8af0 f4aafef3 _76907053">
    <h2>0 notifications</h2>
  </section>

  <section class="_596b43a0 d07cf58d _3ca408df">
    <h2>Sourabh Jha</h2>
    <div class="_80120a9c">AI / LLM Application Engineer — Agents, MCP, and Production Backends</div>
    <span class="ca9ec55">Gurugram, Haryana, India</span>
    <button>Follow</button>
    <img src="https://media.licdn.com/dms/image/v2/D5603AQ/photo.jpg">
  </section>

  <section class="_5b216717 c85c4b08 a9ec5584">
    <h2>About</h2>
    <div class="_530aaf77">I build LLM-powered systems end to end — from the agent pipeline down to the deploy.</div>
  </section>

  <section class="_5b216717 c85c4b08 _99df544f">
    <h2>Activity</h2>
    <p>610 followers</p>
    <p>609 connections</p>
  </section>

  <section class="_5b216717 c85c4b08 _3ca408df">
    <h2>Experience</h2>
    <ul>
      <li>
        <a href="/company/accenture/"><span>Accenture</span></a>
        <span>Associate Software Engineer</span>
        <span>Accenture · Full-time</span>
        <span>Nov 2024 - Present</span>
        <span>Gurugram</span>
      </li>
    </ul>
  </section>

  <section class="_5b216717 c85c4b08 _9012a0c">
    <h2>Skills</h2>
    <ul>
      <li><span>Kubernetes</span></li>
      <li><span>PostgreSQL</span></li>
    </ul>
  </section>
</main></body></html>
"""


def current():
    return dom_profile.parse(BeautifulSoup(CURRENT_HTML, "lxml"), "sk-jha")


def test_current_build_has_no_h1_at_all():
    soup = BeautifulSoup(CURRENT_HTML, "lxml")
    assert soup.select_one("main h1") is None
    assert dom_profile.looks_rendered(soup) is True


def test_name_comes_from_the_title_not_a_heading_scan():
    out = current()
    assert out["scraper_full_name"] == "Sourabh Jha"
    assert out["first_name"] == "Sourabh"
    assert out["last_name"] == "Jha"


def test_headline_and_location_from_the_top_card():
    out = current()
    assert out["linkedin_headline"].startswith("AI / LLM Application Engineer")
    assert out["location"] == "Gurugram, Haryana, India"


def test_sections_are_found_by_heading_text_without_ids():
    soup = BeautifulSoup(CURRENT_HTML, "lxml")
    assert soup.find(id="about") is None
    out = current()
    assert "LLM-powered systems" in out["linkedin_description"]
    assert out["linkedin_job_title"] == "Associate Software Engineer"
    assert out["company_name"] == "Accenture"
    assert out["linkedin_job_date_range"] == "Nov 2024 - Present"
    assert out["linkedin_skills_label"] == "Kubernetes, PostgreSQL"


def test_counts_are_found_outside_the_top_card():
    out = current()
    assert out["linkedin_followers_count"] == 610
    assert out["linkedin_connections_count"] == 609


def test_the_notifications_heading_is_not_mistaken_for_a_person():
    out = current()
    assert out["scraper_full_name"] != "0 notifications"


def test_signed_in_chrome_alone_is_not_a_render():
    shell = """
    <html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
      <section><h2>0 notifications</h2></section>
    </main></body></html>
    """
    assert dom_profile.looks_rendered(BeautifulSoup(shell, "lxml")) is False


TOP_CARD_HTML = """
<html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
  <section>
    <h2>Sourabh Jha</h2>
    <div>AI / LLM Application Engineer — Agents, MCP, and Production Backends</div>
    <div>
      <a href="/company/accenture/"><span>Accenture</span></a>
      <span>·</span>
      <a href="/school/srm-university-haryana/"><span>SRM University Sonepat, Haryana</span></a>
    </div>
    <span>Gurugram, Haryana, India</span>
    <span>500+ connections</span>
    <button>Message</button>
  </section>
  <section><h2>About</h2><div>I build LLM-powered systems end to end, down to the deploy.</div></section>
</main></body></html>
"""


def top_card():
    return dom_profile.parse(BeautifulSoup(TOP_CARD_HTML, "lxml"), "sk-jha")


def test_company_school_line_is_not_mistaken_for_the_location():
    out = top_card()
    assert out["location"] == "Gurugram, Haryana, India"
    assert "Accenture" not in out["location"]


def test_organisations_come_from_the_cards_links():
    out = top_card()
    assert out["company_name"] == "Accenture"
    assert out["linkedin_company_slug"] == "accenture"
    assert out["linkedin_company_url"] == "https://linkedin.com/company/accenture"
    assert out["linkedin_school_name"] == "SRM University Sonepat, Haryana"


def test_headline_survives_the_org_line():
    assert top_card()["linkedin_headline"].startswith("AI / LLM Application Engineer")


def test_capped_connection_count_is_read_as_shown():
    assert top_card()["linkedin_connections_count"] == 500


def test_degree_is_anchored_to_the_owners_name():
    html = """
    <html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
      <section><h2>Sourabh Jha</h2><div>Engineer</div></section>
      <section><h2>About</h2><div>Some text about the person here, long enough.</div></section>
      <section><h2>More profiles for you</h2>
        <div>Someone Else • 1st Recruiter</div>
      </section>
      <section><h2>Activity</h2><div>Sourabh Jha • 3rd+ AI / LLM Engineer</div></section>
    </main></body></html>
    """
    out = dom_profile.parse(BeautifulSoup(html, "lxml"), "sk-jha")
    assert out["connection_degree"] == "3rd+"


CENSUS_HTML = """
<html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
  <section><h2>0 notifications</h2></section>

  <section>
    <h2>Sourabh Jha</h2>
    <div>AI / LLM Application Engineer | Python · Go | Associate SWE @ Accenture</div>
    <div>Accenture · SRM University Sonepat, Haryana</div>
    <span>Gurugram, Haryana, India</span>
    <span>500+ connections</span>
  </section>

  <section>
    <h2>About</h2>
    <div>I build LLM-powered systems end to end, from the agent pipeline down to the deploy.</div>
  </section>

  <section>
    <h2>Experience</h2>
    <div>
      <div>
        <a href="/company/accenture/"><span>Accenture</span></a>
        <span>Associate Software Engineer</span>
        <span>Accenture · Full-time</span>
        <span>Nov 2024 - Present</span>
        <span>Gurugram</span>
      </div>
    </div>
  </section>

  <section>
    <h2>Education</h2>
    <div>
      <div>
        <a href="/school/srm-university-haryana/"><span>SRM University</span></a>
        <span>SRM University Sonepat, Haryana</span>
        <span>Bachelor of Technology - BTech, Computer Science</span>
        <span>Aug 2019 - Aug 2023</span>
      </div>
    </div>
  </section>

  <section>
    <h2>Skills (44)</h2>
    <div>
      <div><span>Kubernetes</span><span>Endorsed</span></div>
      <div><span>PostgreSQL</span><span>Endorsed</span></div>
    </div>
  </section>

  <section>
    <h2>Licenses &amp; certifications</h2>
    <div>
      <div><span>Azure Fundamentals</span><span>Microsoft</span></div>
      <div><span>CKA</span><span>CNCF</span></div>
    </div>
  </section>

  <section>
    <h2>Projects</h2>
    <div>
      <div><span>Freight Dashboard</span><span>2025</span></div>
    </div>
  </section>

  <section>
    <h2>Interests</h2>
    <div>
      <div><span>Anthropic</span><span>Company</span></div>
    </div>
  </section>
</main></body></html>
"""


def census():
    return dom_profile.parse(BeautifulSoup(CENSUS_HTML, "lxml"), "sk-jha")


def test_heading_with_a_count_suffix_is_still_found():
    assert dom_profile.normalise_heading("Skills (44)") == "skills"
    assert dom_profile.heading_count("Skills (44)") == 44
    out = census()
    assert out["linkedin_skills_label"] == "Kubernetes, PostgreSQL"
    assert out["linkedin_skills_count"] == 44


def test_entries_that_are_divs_rather_than_list_items_are_read():
    out = census()
    assert out["linkedin_job_title"] == "Associate Software Engineer"
    assert out["linkedin_job_date_range"] == "Nov 2024 - Present"
    assert out["linkedin_school_degree"] == "Bachelor of Technology - BTech"


def test_plain_text_org_line_does_not_become_the_location():
    out = census()
    assert out["location"] == "Gurugram, Haryana, India"


def test_experience_section_wins_the_company_over_the_top_card():
    out = census()
    assert out["company_name"] == "Accenture"
    assert out["linkedin_company_slug"] == "accenture"


def test_about_is_exposed_under_both_names():
    out = census()
    assert "LLM-powered systems" in out["linkedin_about"]
    assert out["linkedin_about"] == out["linkedin_description"]


def test_the_other_sections_are_captured():
    out = census()
    assert out["linkedin_certifications"] == "Azure Fundamentals, CKA"
    assert out["linkedin_projects"] == "Freight Dashboard"
    assert out["linkedin_interests"] == "Anthropic"


def test_every_section_is_captured_losslessly():
    import json

    captured = json.loads(census()["linkedin_sections_json"])
    for heading in ("about", "experience", "education", "skills", "projects", "interests"):
        assert heading in captured, heading
    assert captured["skills"]["count"] == 44
    assert any("Kubernetes" in " ".join(row) for row in captured["skills"]["rows"])
    assert "0 notifications" not in captured



RICH_HTML = """
<html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
  <section><h2>Sourabh Jha</h2>
    <div>AI / LLM Application Engineer</div>
    <img src="https://media.licdn.com/dms/image/v2/D56/profile-displayphoto-shrink_400_400/x.jpg">
    <img src="https://media.licdn.com/dms/image/v2/D56/profile-backgroundimage-shrink_350_1400/y.jpg">
    <img src="https://media.licdn.com/dms/image/v2/C4E/company-logo_100_100/z.jpg">
  </section>

  <section><h2>Top skills</h2>
    <div>Python · Go · Kubernetes</div>
  </section>

  <section><h2>Experience</h2>
    <div>
      <div>
        <a href="/company/accenture/"><span>Accenture</span></a>
        <span>Associate Software Engineer</span>
        <span>Accenture · Full-time</span>
        <span>Nov 2024 - Present</span>
        <span>Gurugram</span>
        <span>Delivered backend features for enterprise systems and cut deployment time substantially.</span>
      </div>
      <div>
        <a href="/company/somewhere/"><span>Somewhere</span></a>
        <span>Intern</span>
        <span>Somewhere · Internship</span>
        <span>Jan 2023 - Oct 2024</span>
        <span>Remote</span>
      </div>
    </div>
  </section>

  <section><h2>Licenses &amp; certifications</h2>
    <div>
      <div>
        <span>Azure Fundamentals</span>
        <span>Microsoft</span>
        <span>Issued Jan 2024</span>
        <span>Credential ID ABC-123</span>
      </div>
    </div>
  </section>

  <section><h2>Projects</h2>
    <div>
      <div>
        <span>Freight Dashboard</span>
        <span>Jan 2025 - Present</span>
        <span>A logistics dashboard a real business runs its daily operations on.</span>
      </div>
    </div>
  </section>

  <section><h2>Languages</h2>
    <div>
      <div><span>English</span><span>Full professional proficiency</span></div>
      <div><span>Hindi</span><span>Native or bilingual proficiency</span></div>
    </div>
  </section>

  <section><h2>Skills (44)</h2>
    <div>
      <div><span>Kubernetes</span><span>Endorsed by 3 people</span></div>
      <div><span>PostgreSQL</span><span>2 experiences across Accenture</span></div>
    </div>
  </section>
</main></body></html>
"""


def rich():
    import json
    out = dom_profile.parse(BeautifulSoup(RICH_HTML, "lxml"), "sk-jha")
    return out, json


def test_every_experience_entry_is_kept_with_its_description():
    out, json = rich()
    entries = json.loads(out["linkedin_experience_json"])
    assert len(entries) == 2
    assert entries[0]["title"] == "Associate Software Engineer"
    assert entries[0]["company"] == "Accenture"
    assert entries[0]["employment_type"] == "Full-time"
    assert "backend features" in entries[0]["description"]
    assert entries[0]["company_url"].endswith("/company/accenture/")
    assert entries[1]["title"] == "Intern"


def test_certificates_keep_issuer_and_credential_id():
    out, json = rich()
    entry = json.loads(out["linkedin_certifications_json"])[0]
    assert entry["name"] == "Azure Fundamentals"
    assert entry["issuer"] == "Microsoft"
    assert "Jan 2024" in entry["issued"]
    assert "ABC-123" in entry["credential_id"]


def test_projects_keep_dates_and_description():
    out, json = rich()
    entry = json.loads(out["linkedin_projects_json"])[0]
    assert entry["name"] == "Freight Dashboard"
    assert "logistics dashboard" in entry["description"]


def test_languages_keep_proficiency():
    out, json = rich()
    entries = json.loads(out["linkedin_languages_json"])
    assert entries[0] == {"language": "English", "proficiency": "Full professional proficiency"}
    assert entries[1]["language"] == "Hindi"


def test_skill_rows_drop_endorsement_lines():
    out, json = rich()
    assert json.loads(out["linkedin_skills_json"]) == ["Kubernetes", "PostgreSQL"]


def test_top_skills_is_separate_from_the_skills_section():
    out, _ = rich()
    assert out["linkedin_top_skills"] == "Python, Go, Kubernetes"


def test_images_are_cdn_urls_told_apart_by_path_segment():
    out, _ = rich()
    assert "profile-displayphoto" in out["linkedin_profile_image_url"]
    assert "profile-backgroundimage" in out["linkedin_background_image_url"]
    assert "company-logo" not in out["linkedin_profile_image_url"]



SKILLS_DETAIL = """
<html><body><main>
  <ul>
    <li><span>Kubernetes</span><span>Endorsed by 3 people</span></li>
    <li><span>PostgreSQL</span></li>
    <li><span>Terraform</span></li>
    <li><span>Model Context Protocol (MCP)</span></li>
  </ul>
</main></body></html>
"""


def test_detail_url_construction():
    assert dom_profile.detail_url("sk-jha", "skills").endswith("/in/sk-jha/details/skills/")
    assert dom_profile.detail_url("sk-jha", "licenses & certifications").endswith(
        "/in/sk-jha/details/certifications/"
    )


def test_skills_detail_page_returns_every_skill():
    out = dom_profile.parse_detail(SKILLS_DETAIL, "skills")
    import json

    names = json.loads(out["linkedin_skills_json"])
    assert names == ["Kubernetes", "PostgreSQL", "Terraform", "Model Context Protocol (MCP)"]
    assert out["linkedin_skills_count"] == 4
    assert out["linkedin_skills_label"].startswith("Kubernetes, PostgreSQL")


def test_experience_detail_page_syncs_the_flat_columns():
    html = """
    <html><body><main><ul>
      <li>
        <a href="/company/accenture/"><span>Accenture</span></a>
        <span>Associate Software Engineer</span>
        <span>Accenture · Full-time</span>
        <span>Nov 2024 - Present</span>
      </li>
      <li>
        <a href="/company/other/"><span>Other</span></a>
        <span>Intern</span>
        <span>Other · Internship</span>
        <span>Jan 2023 - Oct 2024</span>
      </li>
    </ul></main></body></html>
    """
    out = dom_profile.parse_detail(html, "experience")
    assert out["linkedin_job_title"] == "Associate Software Engineer"
    assert out["company_name"] == "Accenture"
    assert out["linkedin_experience_count"] == 2


def test_unknown_detail_section_is_ignored_rather_than_guessed():
    assert dom_profile.parse_detail("<html><body><main></main></body></html>", "nonsense") == {}



CHROME_DETAIL = """
<html><body>
  <header><a>Skip to main content</a><a>Home</a><a>Jobs</a></header>
  <nav><span>My Network</span><span>Notifications</span></nav>
  <main>
    <div><button>All</button><button>Show all</button><span>Sort by</span></div>
    <ul>
      <li><span>Kubernetes</span><span>Endorsed by 3 people</span></li>
      <li><span>Terraform</span></li>
    </ul>
  </main>
  <footer><span>About</span><span>Accessibility</span></footer>
</body></html>
"""


def test_filter_chips_are_not_skills():
    out = dom_profile.parse_detail(CHROME_DETAIL, "skills")
    import json

    names = json.loads(out["linkedin_skills_json"])
    assert names == ["Kubernetes", "Terraform"]
    assert "All" not in names
    assert "Show all" not in names


def test_navigation_text_is_not_read_as_content():
    soup = BeautifulSoup(CHROME_DETAIL, "lxml")
    lines = dom_profile._text_lines(soup.find("main"))
    for control in ("All", "Show all", "Sort by", "Home", "Jobs"):
        assert control not in lines


def test_a_bare_connection_degree_is_a_badge_not_an_entry():
    assert dom_profile._is_chrome_text("· 3rd+") is True
    assert dom_profile._is_chrome_text("3rd") is True
    assert dom_profile._is_chrome_text("Kubernetes") is False


def test_top_skills_stops_at_the_next_section():
    html = """
    <html><head><title>Sourabh Jha | LinkedIn</title></head><body><main>
      <section><h2>Sourabh Jha</h2>
        <div>Engineer</div>
        <div>Top skills: Python · Go · Kubernetes</div>
      </section>
      <section><h2>Activity</h2><div>610 followers</div></section>
    </main></body></html>
    """
    names = dom_profile.top_skills(BeautifulSoup(html, "lxml"))
    assert names == ["Python", "Go", "Kubernetes"]
    assert not any("Activity" in name for name in names)


PRONOUNS_HTML = """
<html><head><title>Aman Batra | LinkedIn</title></head><body><main>
  <section>
    <h2>Aman Batra</h2>
    <span>He/Him</span>
    <div>I love building AI that feels… usable.</div>
    <span>Gurugram, Haryana, India</span>
    <span>500+ connections</span>
    <button>Message</button>
  </section>
</main></body></html>
"""


def pronoun_card():
    return dom_profile.parse(BeautifulSoup(PRONOUNS_HTML, "lxml"), "aman-batra-dev")


def test_pronouns_are_not_mistaken_for_the_headline():
    out = pronoun_card()
    assert out["linkedin_headline"] == "I love building AI that feels… usable."


def test_pronouns_do_not_push_the_headline_into_the_location():
    out = pronoun_card()
    assert out["location"] == "Gurugram, Haryana, India"


ABOUT_WITH_TOP_SKILLS_HTML = """
<html><head><title>Aman Batra | LinkedIn</title></head><body><main>
  <section><h2>Aman Batra</h2><div>Builder</div></section>
  <section>
    <h2>About</h2>
    <div>I build games and the AI that plays them.</div>
    <div>Top skills</div>
    <div>Unreal Engine • Unity • Game Programming • Neural Networks • Machine Learning</div>
  </section>
</main></body></html>
"""


def test_top_skills_strip_does_not_become_the_about_text():
    out = dom_profile.parse(BeautifulSoup(ABOUT_WITH_TOP_SKILLS_HTML, "lxml"), "aman-batra-dev")
    assert out["linkedin_about"] == "I build games and the AI that plays them."
    assert out["linkedin_description"] == "I build games and the AI that plays them."


UNLINKED_SCHOOL_HTML = """
<html><head><title>Aman Batra | LinkedIn</title></head><body><main>
  <section>
    <h2>Aman Batra</h2>
    <span>He/Him</span>
    <div>I love building AI that feels… usable.</div>
    <div>SRM University Sonepat, Haryana</div>
    <div>New Delhi, Delhi, India</div>
    <span>·</span>
    <a href="/in/aman-batra-dev/overlay/contact-info/">Contact info</a>
    <span>500+</span>
    <span>connections</span>
  </section>
</main></body></html>
"""


def test_unlinked_school_line_does_not_take_the_location():
    out = dom_profile.parse(BeautifulSoup(UNLINKED_SCHOOL_HTML, "lxml"), "aman-batra-dev")
    assert out["location"] == "New Delhi, Delhi, India"


def test_contact_info_is_not_mistaken_for_the_location():
    out = dom_profile.parse(BeautifulSoup(UNLINKED_SCHOOL_HTML, "lxml"), "aman-batra-dev")
    assert out["location"] != "Contact info"


NOISY_ACTIVITY_HTML = """
<html><head><title>Aman Batra | LinkedIn</title></head><body><main>
  <section>
    <h2>Aman Batra</h2>
    <div>I love building AI that feels… usable.</div>
    <div>New Delhi, Delhi, India</div>
  </section>
  <section>
    <h2>Activity</h2>
    <ul><li>
      <span>Shipped a new build today</span>
      <span>Video Player is loading.</span>
      <span>Current Time</span><span>0:00</span><span>/</span>
      <span>Duration</span><span>1:53</span>
      <span>Loaded</span><span>0%</span><span>1.71%</span><span>Stream Type</span>
    </li></ul>
  </section>
</main></body></html>
"""


def noisy_sections():
    import json
    out = dom_profile.parse(BeautifulSoup(NOISY_ACTIVITY_HTML, "lxml"), "aman-batra-dev")
    return json.loads(out.get("linkedin_sections_json") or "{}")


def test_the_persons_own_name_is_not_a_section():
    assert "aman batra" not in noisy_sections()


def test_video_player_controls_are_not_row_content():
    rows = noisy_sections().get("activity", {}).get("rows", [])
    flat = [cell for row in rows for cell in row]
    for noise in ("Video Player is loading.", "Current Time", "Duration", "Stream Type", "0:00", "0%", "1.71%"):
        assert noise not in flat, f"{noise!r} leaked into activity rows"
    assert "Shipped a new build today" in flat


def test_unlinked_school_line_is_captured_as_the_school():
    out = dom_profile.parse(BeautifulSoup(UNLINKED_SCHOOL_HTML, "lxml"), "aman-batra-dev")
    assert out["linkedin_school_name"] == "SRM University Sonepat, Haryana"


CURRENT_BUILD_HTML = """
<html><head><title>Aman Batra | LinkedIn</title></head><body><main>
  <section><h2>Aman Batra</h2><div>Builder</div><div>New Delhi, Delhi, India</div></section>
  <section>
    <h2>About</h2>
    <span tabindex="-1" data-testid="expandable-text-box">
      Hey, I am Aman 👋 I like building AI tools<br>that quietly make life easier.
      <button>…see more</button>
    </span>
  </section>
  <section>
    <h2>Experience</h2>
    <ul>
      <li></li>
      <li>
        <div><span>Artificial Intelligence Engineer</span></div>
        <a href="/company/76798322/"><img src="logo.png"/></a>
        <span>Arlox.io · Full-time</span>
        <span>Nov 2025 - Present · 10 mos</span>
        <span>Gurugram, Haryana, India · On-site</span>
        <span data-testid="expandable-text-box">- Building inhouse Micro AI Agents</span>
      </li>
    </ul>
  </section>
</main></body></html>
"""


def current_build():
    return dom_profile.parse(BeautifulSoup(CURRENT_BUILD_HTML, "lxml"), "aman-batra-dev")


def test_prose_box_is_read_whole_for_the_about_text():
    out = current_build()
    assert out["linkedin_about"].startswith("Hey, I am Aman")
    assert "that quietly make life easier." in out["linkedin_about"]


def test_see_more_affordance_is_not_part_of_the_text():
    out = current_build()
    assert "see more" not in out["linkedin_about"].lower()


def test_empty_leading_row_does_not_blank_the_top_experience_entry():
    out = current_build()
    assert out["linkedin_job_title"] == "Artificial Intelligence Engineer"
    assert out["company_name"] == "Arlox.io"
    assert out["linkedin_job_date_range"] == "Nov 2025 - Present · 10 mos"


def test_role_description_comes_from_the_main_page_not_only_details():
    out = current_build()
    assert out["linkedin_job_description"] == "- Building inhouse Micro AI Agents"
