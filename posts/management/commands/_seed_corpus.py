"""The hand-authored demo corpus. **This file is content, not code.**

`testing.md` §7.1 is the whole reason it exists, and the reasoning is worth
repeating at the top of the file so nobody "improves" it into Faker later:

> `Faker.text()` produces "Lorem ipsum dolor sit amet" or, worse,
> plausible-looking sentence salad. A visitor reads two post bodies and knows
> instantly the site is fake, and that impression is unrecoverable — it lands
> before they've seen a single feature.

So **Faker generates names, handles, dates and filler; it does not generate the
ideas.** Everything below was written by hand to be read.

Jeni: this is the file to edit. Nothing here is load-bearing on code —
`seed_demo.py` reads these lists and nothing else cares about the wording. Cut a
post you don't like, rewrite a bio that doesn't sound like a person, change a
title. The only things that must stay structurally valid are:

* every `field` and every entry in `tags` / `interests` is a tag **name** —
  curated ones must match `posts/migrations/0002` exactly (they are looked up by
  slug, so "Craft & Small Business" is fine, "craft and small business" is a new
  tag);
* every entry in `roles` / `skills` is a **curated role slug** from that same
  migration — the role filter is exact-match, so a typo here is a post that can
  never be found by the joiner's primary path (ADR-0004);
* **every post names at least one role** (Decision F, Jeni, 3 Oct 2026).
  `posts.services.create_post` does not enforce it — the form does — but a post
  with no roles cannot be matched or filtered, so the corpus satisfies it and
  `tests/cross/test_seed_demo.py` asserts it;
* at most 5 tags (`MAX_TAGS_PER_POST`), 3 `custom_roles`, 3 `custom_skills`;
* bodies stay under 200 words-ish and over 60 — see the note on uniformity below.

**On uniformity.** Bodies deliberately vary in length and polish. Some are three
tidy paragraphs, some are one excited run-on with a stray comma. Real
communities are not uniformly well-written, and uniformity is what reads as
synthetic — it is the same tell as every post saying "2 minutes ago".

**The crochet case is mandatory.** `product-spec.md` §1 names it, so it is in
here by name (`priya_ramesh`, "I run a crochet business…"). If that post ever
disappears from this file, the spec's own worked example stops being
demonstrable on the deployed site.

Fields covered, per §7.1: software · AI & data · hardware/IoT · craft & small
business · food · campus & civic · fintech · edtech · climate · content/media ·
health & fitness · games · design · e-commerce · social impact.
"""

# ── People ───────────────────────────────────────────────────────────────────
#
# ~20 believable users. `username` is the public handle and goes in URLs, so it
# follows `[a-z0-9_]{3,30}`. `field` must be a CURATED tag name — it becomes
# `Profile.field_tag`, which is what Home tier 2 matches on.
#
# `skills` are curated role slugs ("roles you can fill", spec §4.1).
# `custom_skills` is the free-text "Other" path (ADR-0004), max 3, searchable
# but never filterable — about a third of these carry one so the path is visible
# in the demo.

PEOPLE = [
    {
        "username": "aarti_nair",
        "display_name": "Aarti Nair",
        "headline": "Final-year CS student, obsessed with Indian-language NLP",
        "occupation": "Student, PES University",
        "bio": (
            "I spent last summer labelling Kannada news articles by hand for a lab "
            "project and came away convinced the tooling is the bottleneck, not the "
            "models. Mostly I build small things and write them up. Happy to pair on "
            "anything involving messy text."
        ),
        "city": "Bengaluru",
        "field": "AI & Data",
        "purpose": "both",
        "skills": ["ml-engineer", "data-scientist", "backend-developer"],
        "custom_skills": ["Dataset labelling", "Kannada"],
        "interests": ["AI & Data", "Software", "Edtech"],
        "work_done": "Two Kaggle write-ups, one lab project on Kannada NER.",
        "github_url": "https://github.com/aarti-nair",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "rohan_mehta",
        "display_name": "Rohan Mehta",
        "headline": "Embedded engineer. I like problems that have a smell.",
        "occupation": "Firmware engineer",
        "bio": (
            "Six years of firmware, mostly motor control and sensors. I have a drawer "
            "of half-finished boards and a 3D printer that works four days out of "
            "five. I am looking for one project to actually finish."
        ),
        "city": "Pune",
        "field": "Hardware & IoT",
        "purpose": "find",
        "skills": ["embedded-engineer", "hardware-engineer"],
        "custom_skills": ["PCB layout", "KiCad"],
        "interests": ["Hardware & IoT", "Climate"],
        "work_done": "Shipped firmware on two industrial products.",
        "github_url": "https://github.com/rohanmehta",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "priya_ramesh",
        "display_name": "Priya Ramesh",
        "headline": "I run a crochet business out of my living room",
        "occupation": "Owner, Loop & Thread",
        "bio": (
            "Four years of crochet — bags, baby things, the occasional cardigan that "
            "takes a month. I sell on Instagram and at two weekend markets in Chennai. "
            "I know my craft and I know my customers. What I do not know is anything "
            "about websites, and every quote I have been given is more than I make in "
            "a quarter. I would rather learn alongside someone than hire a stranger."
        ),
        "city": "Chennai",
        "field": "Craft & Small Business",
        "purpose": "post",
        "skills": ["textile-craft-maker", "photographer"],
        "custom_skills": ["Crochet", "Pattern design"],
        "interests": ["Craft & Small Business", "E-commerce", "Design"],
        "work_done": "4 years trading, ~900 Instagram followers, two market stalls.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "sameer_iqbal",
        "display_name": "Sameer Iqbal",
        "headline": "Backend engineer. Payments, reluctantly.",
        "occupation": "Senior engineer, fintech",
        "bio": (
            "I have spent four years in and around UPI integrations, which has made me "
            "extremely boring at parties and quite useful on a payments bug. Looking "
            "for a side project with no reconciliation in it whatsoever."
        ),
        "city": "Hyderabad",
        "field": "Fintech",
        "purpose": "both",
        "skills": ["backend-developer", "devops-engineer", "full-stack-developer"],
        "custom_skills": [],
        "interests": ["Fintech", "Software"],
        "work_done": "Built the settlement pipeline at my current job.",
        "github_url": "https://github.com/sameeriqbal",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "nandini_rao",
        "display_name": "Nandini Rao",
        "headline": "Product designer — mobile first, always",
        "occupation": "Product designer",
        "bio": (
            "I design for people on 4G with cracked screens, which is most people. "
            "Five years in, two of them at a company that made me do real usability "
            "testing in three languages, and I am grateful for it. I will happily do "
            "the design for a project if someone else will own the build."
        ),
        "city": "Bengaluru",
        "field": "Design",
        "purpose": "find",
        "skills": ["product-designer", "ui-designer", "ux-designer", "user-researcher"],
        "custom_skills": ["Figma systems"],
        "interests": ["Design", "Software", "Edtech"],
        "work_done": "Design system used across four products.",
        "github_url": "",
        "portfolio_url": "https://nandinirao.design",
        "website_url": "",
    },
    {
        "username": "imogen_clarke",
        "display_name": "Imogen Clarke",
        "headline": "Climate data analyst, ex-council",
        "occupation": "Data analyst",
        "bio": (
            "I worked three years inside a city council trying to get air quality data "
            "out of PDFs and into something anyone could use. I left. I still want to "
            "solve it, just with fewer committees."
        ),
        "city": "Manchester",
        "field": "Climate",
        "purpose": "both",
        "skills": ["data-scientist", "business-analyst"],
        "custom_skills": ["GIS", "Open data"],
        "interests": ["Climate", "Campus & Civic", "AI & Data"],
        "work_done": "Published an open dataset on ward-level emissions.",
        "github_url": "https://github.com/imogenclarke",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "tashi_dorji",
        "display_name": "Tashi Dorji",
        "headline": "Taught maths for nine years. Now building the thing I wanted.",
        "occupation": "Teacher",
        "bio": (
            "Nine years teaching secondary maths, the last three with a class where "
            "half the students shared four phones between them. Every edtech product I "
            "was shown assumed one device per child and a stable connection. I would "
            "like to build the one that doesn't."
        ),
        "city": "Thimphu",
        "field": "Edtech",
        "purpose": "post",
        "skills": ["mentor-advisor", "writer", "product-manager"],
        "custom_skills": ["Curriculum design"],
        "interests": ["Edtech", "Social Impact"],
        "work_done": "Paper worksheets used by about 40 teachers locally.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "karthik_s",
        "display_name": "Karthik Subramanian",
        "headline": "Cloud kitchen operator. Two stoves, one spreadsheet.",
        "occupation": "Founder, Thatte Idli Co.",
        "bio": (
            "Running a two-stove kitchen doing about 60 orders a day. The food is "
            "sorted. The part that is killing me is knowing what to prep by Thursday "
            "evening, which right now is me and a spreadsheet and a lot of guessing."
        ),
        "city": "Coimbatore",
        "field": "Food & Drink",
        "purpose": "both",
        "skills": ["chef-food-maker", "operations-lead"],
        "custom_skills": ["Kitchen ops"],
        "interests": ["Food & Drink", "E-commerce"],
        "work_done": "18 months trading, ~60 orders/day.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "zara_haq",
        "display_name": "Zara Haq",
        "headline": "Video editor who would quite like to stop editing other people's work",
        "occupation": "Freelance editor",
        "bio": (
            "Four years of cutting other people's documentaries. I have strong opinions "
            "about pacing and a hard drive full of ideas I have never had a reason to "
            "finish. I am good at the craft and genuinely bad at the business side, so "
            "I am looking for someone who finds that part fun."
        ),
        "city": "Karachi",
        "field": "Content & Media",
        "purpose": "find",
        "skills": ["video-editor", "content-creator", "motion-designer"],
        "custom_skills": ["Colour grading"],
        "interests": ["Content & Media", "Social Impact"],
        "work_done": "Two short documentaries, one festival selection.",
        "github_url": "",
        "portfolio_url": "https://zarahaq.cc",
        "website_url": "",
    },
    {
        "username": "ananya_bose",
        "display_name": "Ananya Bose",
        "headline": "Public policy MA. Interested in the boring plumbing of cities.",
        "occupation": "Student, policy research",
        "bio": (
            "I write about municipal service delivery, which is a polite way of saying "
            "I read a lot of tender documents. There is an enormous amount of useful "
            "information locked in formats nobody can read, and I think that is a "
            "software problem wearing a government hat."
        ),
        "city": "Kolkata",
        "field": "Campus & Civic",
        "purpose": "both",
        "skills": ["business-analyst", "writer", "user-researcher"],
        "custom_skills": ["Policy research", "Bengali"],
        "interests": ["Campus & Civic", "Social Impact", "AI & Data"],
        "work_done": "Two published policy briefs.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "https://ananyabose.in",
    },
    {
        "username": "mateo_rivas",
        "display_name": "Mateo Rivas",
        "headline": "Frontend dev. I make things feel fast.",
        "occupation": "Frontend engineer",
        "bio": (
            "Three years of React and a quietly growing suspicion that most of it was "
            "unnecessary. These days I reach for the smallest thing that works. Based "
            "in Bogotá, happy to work across time zones, genuinely enjoy code review."
        ),
        "city": "Bogotá",
        "field": "Software",
        "purpose": "find",
        "skills": ["frontend-developer", "full-stack-developer", "ui-designer"],
        "custom_skills": [],
        "interests": ["Software", "Design", "Games"],
        "work_done": "Rewrote a checkout flow; load time down 60%.",
        "github_url": "https://github.com/mateorivas",
        "portfolio_url": "https://mateo.dev",
        "website_url": "",
    },
    {
        "username": "vikram_joshi",
        "display_name": "Vikram Joshi",
        "headline": "D2C operations. I know where the money leaks.",
        "occupation": "Operations lead",
        "bio": (
            "Six years running fulfilment and returns for small direct-to-consumer "
            "brands. I have seen roughly forty of them from the inside and the same "
            "three things kill most of them. Happy to advise, keen to build."
        ),
        "city": "Ahmedabad",
        "field": "E-commerce",
        "purpose": "both",
        "skills": ["operations-lead", "growth-lead", "partnerships-lead"],
        "custom_skills": ["Logistics", "Returns"],
        "interests": ["E-commerce", "Craft & Small Business"],
        "work_done": "Scaled a brand from 20 to 400 orders a day.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "sneha_kulkarni",
        "display_name": "Sneha Kulkarni",
        "headline": "Physiotherapist. Most fitness apps are designed for the already-fit.",
        "occupation": "Physiotherapist",
        "bio": (
            "I see about thirty patients a week, most of them recovering from something "
            "and most of them given a paper sheet of exercises they will not do. I know "
            "exactly what the content should be. I have no idea how to build an app."
        ),
        "city": "Nashik",
        "field": "Health & Fitness",
        "purpose": "post",
        "skills": ["mentor-advisor", "content-creator"],
        "custom_skills": ["Rehab programming", "Marathi"],
        "interests": ["Health & Fitness", "Edtech"],
        "work_done": "A paper rehab protocol used in two clinics.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "olu_adeyemi",
        "display_name": "Olu Adeyemi",
        "headline": "Community organiser, Lagos. I am good at getting people in a room.",
        "occupation": "Community manager",
        "bio": (
            "I have run a 2,000-person maker community for three years, mostly over "
            "WhatsApp, which is both the reason it works and the reason it is painful. "
            "If your idea needs its first hundred users, that part I can do."
        ),
        "city": "Lagos",
        "field": "Social Impact",
        "purpose": "both",
        "skills": ["community-manager", "marketer", "partnerships-lead"],
        "custom_skills": ["Event ops"],
        "interests": ["Social Impact", "Campus & Civic", "Craft & Small Business"],
        "work_done": "Grew a maker community to ~2,000 members.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "https://olu.ng",
    },
    {
        "username": "farah_siddiqui",
        "display_name": "Farah Siddiqui",
        "headline": "QA. I will find the thing your demo was hiding.",
        "occupation": "QA engineer",
        "bio": (
            "Five years of testing, three of them on a payments product where being "
            "wrong was expensive. I am the person who asks what happens on a flaky "
            "connection, and I promise I am asking because I want the thing to work."
        ),
        "city": "New Delhi",
        "field": "Software",
        "purpose": "find",
        "skills": ["qa-engineer", "backend-developer"],
        "custom_skills": ["Playwright", "Urdu"],
        "interests": ["Software", "Fintech"],
        "work_done": "Built the regression suite at two companies.",
        "github_url": "https://github.com/farahsiddiqui",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "ishan_gupta",
        "display_name": "Ishan Gupta",
        "headline": "Unity dev. Four finished games, thirty unfinished ones.",
        "occupation": "Game developer",
        "bio": (
            "I have shipped four small games, two of which made actual money, and I "
            "have learned that the hard part is never the code. Looking for an artist "
            "I can actually finish something with."
        ),
        "city": "Noida",
        "field": "Games",
        "purpose": "both",
        "skills": ["full-stack-developer", "animator"],
        "custom_skills": ["Unity", "Game feel"],
        "interests": ["Games", "Software", "Content & Media"],
        "work_done": "4 released games, ~80k downloads total.",
        "github_url": "https://github.com/ishangupta",
        "portfolio_url": "https://ishan.games",
        "website_url": "",
    },
    {
        "username": "meera_pillai",
        "display_name": "Meera Pillai",
        "headline": "Marine biologist. The data exists; nobody can read it.",
        "occupation": "Researcher",
        "bio": (
            "I study coastal water quality along the Kerala coast. We collect good data "
            "and publish it as PDFs, which is a bit like writing a letter and burying "
            "it. I would like to fix the last mile."
        ),
        "city": "Kochi",
        "field": "Climate",
        "purpose": "post",
        "skills": ["data-scientist", "writer", "mentor-advisor"],
        "custom_skills": ["Field sampling", "Malayalam"],
        "interests": ["Climate", "Social Impact", "AI & Data"],
        "work_done": "Six years of monthly sampling data, unpublished.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "lin_wei",
        "display_name": "Lin Wei",
        "headline": "ML engineer, Singapore. Suspicious of benchmarks.",
        "occupation": "ML engineer",
        "bio": (
            "I work on recommendation systems, which has taught me that most of the "
            "win is in the data pipeline and most of the credit goes to the model. "
            "Weekends free, interested in anything with a real feedback loop."
        ),
        "city": "Singapore",
        "field": "AI & Data",
        "purpose": "find",
        "skills": ["ml-engineer", "data-scientist", "backend-developer"],
        "custom_skills": [],
        "interests": ["AI & Data", "Fintech", "Software"],
        "work_done": "Recsys serving a few million daily requests.",
        "github_url": "https://github.com/linwei",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "harpreet_kaur",
        "display_name": "Harpreet Kaur",
        "headline": "Textile maker working with phulkari. Slow by design.",
        "occupation": "Maker",
        "bio": (
            "I work with eleven women in two villages near Chandigarh doing phulkari "
            "embroidery. We are good. We are also invisible beyond a 30km radius, and "
            "every marketplace that has approached us wanted a margin that would leave "
            "the women earning less than they do now."
        ),
        "city": "Chandigarh",
        "field": "Craft & Small Business",
        "purpose": "post",
        "skills": ["textile-craft-maker", "operations-lead"],
        "custom_skills": ["Phulkari", "Punjabi"],
        "interests": ["Craft & Small Business", "Social Impact", "E-commerce"],
        "work_done": "A collective of 11 artisans, trading three years.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
    {
        "username": "daniel_osei",
        "display_name": "Daniel Osei",
        "headline": "Growth, fintech, Accra. I have run out of growth hacks and it was a relief.",
        "occupation": "Growth lead",
        "bio": (
            "Four years doing growth for a lending product in Ghana. The thing that "
            "actually moved the number was fixing onboarding, twice. I am sceptical of "
            "most marketing and quite good at the unglamorous parts."
        ),
        "city": "Accra",
        "field": "Fintech",
        "purpose": "both",
        "skills": ["growth-lead", "marketer", "product-manager"],
        "custom_skills": ["Onboarding funnels"],
        "interests": ["Fintech", "Social Impact"],
        "work_done": "Took a lending app from 4k to 90k users.",
        "github_url": "",
        "portfolio_url": "",
        "website_url": "",
    },
]


# ── The three demo accounts (§7.5) ───────────────────────────────────────────
#
# Hand-written too, because `demo@` is the account a stranger logs into from the
# login screen — it is the single most-read profile on the deployed site.
#
# `username` and `email` here are **contract**, not content: `product-spec.md`
# §5.3 prints these credentials on the login screen and `testing.md` §7.5 names
# the addresses. Change the bios freely; changing the addresses changes the
# login screen and the tests.

DEMO_ACCOUNTS = {
    "demo": {
        "username": "demo_maya",
        "email": "demo@alongside.app",
        "display_name": "Maya Krishnan",
        "headline": "Browsing on behalf of everyone who hasn't signed up yet",
        "occupation": "Product manager",
        "bio": (
            "This is the shared demo account — you are logged in as me so you can see "
            "what the signed-in experience looks like without making one. I have three "
            "ideas posted, a few people I follow and some saved posts. You can browse, "
            "spark and save from here; posting, commenting and DMing need an account of "
            "your own."
        ),
        "city": "Bengaluru",
        "field": "Software",
        "purpose": "both",
        "skills": ["product-manager", "user-researcher"],
        "custom_skills": ["Workshops"],
        "interests": ["Software", "Design", "AI & Data"],
        "work_done": "Shipped three products, two of which worked.",
    },
    "new": {
        "username": "demo_newcomer",
        "email": "demo.new@alongside.app",
        "display_name": "Arjun Verma",
        "headline": "Just signed up. Haven't done anything yet.",
        # Deliberately short, and deliberately the only thing filled in. This
        # account exists to show the cold-start experience (§7.5): no follows,
        # no interests, no posts. A `field_tag` IS set, so Home tier 2 is what a
        # visitor sees — which is the star feature, and §7.2 invariant 1 is what
        # guarantees it has rows to show.
        "bio": "",
        "occupation": "",
        "city": "",
        "field": "Design",
        "purpose": "find",
        "skills": [],
        "custom_skills": [],
        "interests": [],
        "work_done": "",
    },
    "mod": {
        "username": "demo_moderator",
        "email": "demo.mod@alongside.app",
        "display_name": "Moderation Demo",
        "headline": "Staff account for the report queue — view and change reports only",
        "bio": (
            "A deliberately restricted staff account so the moderation queue is "
            "demonstrable. It can view and update reports and nothing else: no delete "
            "permission on any model, not a superuser, no access to users or posts in "
            "admin."
        ),
        "occupation": "",
        "city": "",
        "field": "Software",
        "purpose": "find",
        "skills": [],
        "custom_skills": [],
        "interests": [],
        "work_done": "",
    },
}


# ── Posts ────────────────────────────────────────────────────────────────────
#
# ~60 ideas. `seed_demo --posts N` takes a deterministic subset, thinned so the
# per-author shape stays the power law §7.2 asks for at any N.
#
# **Every post has an author, and the author is chosen to make sense.** The
# physiotherapist posts the rehab app; the crochet maker posts the crochet shop.
# Random author assignment is the second most obvious tell after lorem ipsum — a
# firmware engineer posting about embroidery reads wrong instantly, even to
# someone who could not say why.
#
# The per-author counts here ARE the distribution: a few authors post a lot,
# most post two to five, and **four authors post nothing at all** — all four of
# whom have `purpose: "find"` in PEOPLE above, because the person who only wants
# to join things is exactly the person with an empty profile tab. That satisfies
# §7.2 invariant 2 ("≥1 user with zero posts") by construction, not by sampling.
#
# `stage`: idea | building | launched     `commitment`: casual | serious
# `tags`: up to 5 tag NAMES (curated or free text — free text is the norm,
#         ADR-0004). Most posts carry at least one curated tag, because Home
#         tier 2 matches a curated `field_tag` against post tags and a corpus
#         with no curated tags makes the star feature return nothing (§7.1).
# `roles`: curated role slugs. **Never empty** (Decision F, Jeni 3 Oct 2026).
# `custom_roles`: the free-text "Other" path, on about a fifth of the corpus.

POSTS = [
    # ── Craft & small business — the case product-spec.md §1 names ──────────
    {
        "author": "priya_ramesh",
        "title": "I run a crochet business and I need an actual shop, not an Instagram DM",
        "body": (
            "Right now someone sees a bag on my Instagram, DMs me, I send a price, they "
            "send a screenshot of a payment, and I write the address in a notebook. It "
            "works until it doesn't — last month I lost an order entirely because the "
            "message request went to a folder I didn't know existed.\n\n"
            "What I want is simple and I know it is not hard for someone who does this "
            "for a living: a page per product, a cart, a payment link, and an email when "
            "something sells. I do not need an app. I do not need a logo redesign. I have "
            "good photos because I take them myself.\n\n"
            "I can pay a little, but honestly what I am offering is a real small business "
            "with real customers to put in your portfolio, and I will send you things I "
            "have made. I learn fast and I will not disappear halfway."
        ),
        "tags": ["Craft & Small Business", "E-commerce", "crochet", "small business"],
        "roles": ["frontend-developer", "full-stack-developer"],
        "custom_roles": ["Shopify generalist"],
        "stage": "idea",
        "commitment": "casual",
        "city": "Chennai",
        "remote": True,
    },
    {
        "author": "priya_ramesh",
        "title": "A crochet pattern app that isn't just a PDF you lose",
        "body": (
            "Every pattern I buy arrives as a PDF that I print, lose, and re-download. "
            "Nobody has built the obvious thing: a pattern you follow on a phone, with a "
            "row counter that remembers where you were when you put it down three days "
            "ago.\n\n"
            "I have about forty of my own patterns written up and I know twenty makers who "
            "would put theirs on it. The hard part is the counter being genuinely pleasant "
            "to use one-handed with yarn in the other, which is a design problem."
        ),
        "tags": ["Craft & Small Business", "crochet", "patterns"],
        "roles": ["android-developer", "ui-designer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Chennai",
        "remote": True,
    },
    {
        "author": "priya_ramesh",
        "title": "Weekend market stall finder for makers in Chennai",
        "body": (
            "Finding out about a weekend market here is entirely word of mouth and "
            "WhatsApp forwards. Half the time I hear about a market after the stalls have "
            "filled. I keep a list of organisers in my notes app and I would happily turn "
            "it into something public — dates, stall fees, footfall if anyone knows it, "
            "and who to contact.\n\n"
            "Very small idea. Someone who can put up a simple site and a form would have "
            "it done in a weekend, and about two hundred makers in this city would use it."
        ),
        "tags": ["Craft & Small Business", "Campus & Civic", "markets", "chennai"],
        "roles": ["frontend-developer", "community-manager"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Chennai",
        "remote": False,
    },
    {
        "author": "priya_ramesh",
        "title": "Want to shoot a 60-second video of how a crochet bag actually gets made",
        "body": (
            "People buy more when they can see the hours. I have tried filming it myself "
            "on a phone propped against a jar and it looks exactly as bad as that sounds. "
            "One afternoon in my living room, decent light, me working, close on the "
            "hands. I will feed you extremely well."
        ),
        "tags": ["Craft & Small Business", "Content & Media", "video"],
        "roles": ["video-editor", "photographer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Chennai",
        "remote": False,
    },
    {
        "author": "priya_ramesh",
        "title": "I teach crochet to ten people a weekend — should this be a proper business?",
        "body": (
            "I have been running informal classes in a cafe on Sundays. Ten people, two "
            "hours, everyone leaves with a coaster. It is the most profitable thing I do "
            "per hour and I have never advertised it once.\n\n"
            "I think there is a small business here and I do not know how to think about "
            "it — bookings, deposits, kits posted out, maybe an online version. Would like "
            "to talk to someone who has turned a skill into a class before, even if "
            "nothing comes of it."
        ),
        "tags": ["Craft & Small Business", "Edtech", "teaching"],
        "roles": ["mentor-advisor", "operations-lead"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Chennai",
        "remote": False,
    },
    # ── AI & data, campus ───────────────────────────────────────────────────
    {
        "author": "aarti_nair",
        "title": "Open annotation tool for Indian-language text that doesn't assume English",
        "body": (
            "Every labelling tool I have used tokenises on whitespace, falls over on "
            "Devanagari, mangles conjuncts in the display, and has no concept of a script "
            "other than Latin. Last summer we spent more time fighting the tool than "
            "labelling.\n\n"
            "What I want to build is small and opinionated: a web app where you load a CSV "
            "of sentences, define a label set, and annotate with keyboard shortcuts that "
            "actually work in Kannada, Hindi, Tamil and Bengali. Export to something a "
            "training script can read. No accounts, no cloud, runs on a laptop.\n\n"
            "I can do the backend and the linguistics. I need someone who cares about text "
            "rendering more than I do, because that is where this lives or dies."
        ),
        "tags": ["AI & Data", "Software", "nlp", "open source", "indic"],
        "roles": ["frontend-developer", "ml-engineer"],
        "custom_roles": ["Typography nerd"],
        "stage": "building",
        "commitment": "serious",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "author": "aarti_nair",
        "title": "Why does every college placement portal look like it was built in 2009",
        "body": (
            "Ours loses your resume if you press the back button. There are three thousand "
            "students on it. I have complained, politely, twice.\n\n"
            "I want to build the version that works, and I think the way in is to build it "
            "for one department first and let it spread. Upload once, apply with two taps, "
            "get a notification that is not an email from a noreply address. The data model "
            "is genuinely easy. The hard part is persuading a placement office to let us try, "
            "so I would love someone who is good at talking to administrators."
        ),
        "tags": ["Campus & Civic", "Software", "campus", "placements"],
        "roles": ["backend-developer", "product-manager", "ux-designer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "author": "aarti_nair",
        "title": "Flashcards for students who share one phone between four people",
        "body": (
            "Anki assumes the phone is yours. In a lot of households it is not. Everything "
            "breaks: streaks shame the wrong person, the review queue belongs to whoever "
            "opened it last, and there is no way to say 'I am Meena now'.\n\n"
            "Profiles behind a four-digit switch, offline-first, under 10MB. I have a "
            "working scheduler already. Looking for someone who wants to own the Android "
            "side properly, and ideally a teacher who will tell me when I am wrong about "
            "what students need."
        ),
        "tags": ["Edtech", "AI & Data", "offline first", "students"],
        "roles": ["android-developer", "product-designer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "serious",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "author": "aarti_nair",
        "title": "Looking for a co-founder for a tiny invoice-reading tool",
        "body": (
            "Small businesses get invoices as photos on WhatsApp. Somebody then types them "
            "into a ledger by hand. That is the entire problem and it is worth money.\n\n"
            "I can build the extraction. I am 22 and I have never sold anything to anyone, "
            "which is the actual gap. Looking for someone who has, and who is happy starting "
            "with ten customers in one city rather than a pitch deck."
        ),
        "tags": ["AI & Data", "Fintech", "ocr", "small business"],
        "roles": ["co-founder", "sales-lead"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "author": "aarti_nair",
        "title": "Weekend project: a readable diff viewer for Jupyter notebooks",
        "body": (
            "Notebook diffs are unreadable and everyone has quietly accepted it. I want a "
            "small web tool: drop two .ipynb files in, see a cell-level diff with outputs "
            "collapsed by default. No install, no git integration, no accounts. Three "
            "weekends at most. I mostly want someone to do it with so that it actually "
            "gets finished."
        ),
        "tags": ["Software", "AI & Data", "developer tools", "open source"],
        "roles": ["frontend-developer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "author": "aarti_nair",
        "title": (
            "One calendar for every college society event, instead of "
            "forty Instagram accounts"
        ),
        "body": (
            "There are forty societies on my campus and every one announces things on its "
            "own account. You find out about the thing you would have loved the day after "
            "it happened.\n\n"
            "Scrape nothing, ask nicely: one form per society, one calendar out. I will do "
            "the backend and the asking. Looking for a designer, because the entire product "
            "is one screen and that screen has to be good."
        ),
        "tags": ["Campus & Civic", "campus", "events"],
        "roles": ["ui-designer", "backend-developer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Bengaluru",
        "remote": False,
    },
    # ── Fintech ─────────────────────────────────────────────────────────────
    {
        "author": "sameer_iqbal",
        "title": "Shared expenses for flatmates who stop speaking by month four",
        "body": (
            "Splitwise is fine, and I have watched three flats stop using it for the same "
            "reason: the person who pays for most things stops entering them, and once the "
            "ledger is wrong everybody abandons it.\n\n"
            "My theory is that entry has to be zero-effort or it does not happen. If you "
            "can forward a payment confirmation and have it land in the right split, the "
            "ledger stays true. I have the parsing side covered.\n\n"
            "Looking for someone to own mobile, and genuinely for someone who has lived in "
            "a shared flat recently enough to still be annoyed about it."
        ),
        "tags": ["Fintech", "Software", "upi", "personal finance"],
        "roles": ["android-developer", "product-designer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "serious",
        "city": "Hyderabad",
        "remote": True,
    },
    {
        "author": "sameer_iqbal",
        "title": "Chit-fund bookkeeping, but not in a pencil notebook",
        "body": (
            "My aunt runs a twenty-person chit fund out of a notebook. Hundreds of "
            "thousands of rupees, tracked in pencil, and it works because everyone trusts "
            "her. When she stops, it stops.\n\n"
            "I do not want to disrupt anything. I want the notebook, on a phone, in Telugu, "
            "that she can use without help and that prints a page anyone can check. This is "
            "a design problem far more than an engineering one."
        ),
        "tags": ["Fintech", "Social Impact", "bookkeeping", "regional languages"],
        "roles": ["ux-designer", "backend-developer", "translator"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Hyderabad",
        "remote": True,
    },
    {
        "author": "sameer_iqbal",
        "title": "Open-source payment reconciliation library — want to maintain it with me?",
        "body": (
            "I have written essentially the same settlement-matching code at two jobs and I "
            "am fairly sure a few hundred people are writing it again this month. I would "
            "like to extract the boring, correct version and publish it properly: tests, "
            "docs, a changelog, the lot.\n\n"
            "I am looking for one other maintainer, mostly so it survives me losing interest."
        ),
        "tags": ["Fintech", "Software", "open source", "payments"],
        "roles": ["backend-developer", "qa-engineer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Hyderabad",
        "remote": True,
    },
    {
        "author": "sameer_iqbal",
        "title": "Tiny tool: what do my mutual fund fees actually cost me over ten years",
        "body": (
            "Every fact sheet gives you an expense ratio and no intuition whatsoever. I "
            "want one input box and one chart that says: here is the number, in rupees, "
            "that you will not have. Nothing else. No sign-up, no lead capture, no "
            "affiliate links — which is precisely why nobody has built it."
        ),
        "tags": ["Fintech", "personal finance", "calculator"],
        "roles": ["frontend-developer", "writer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Hyderabad",
        "remote": True,
    },
    {
        "author": "sameer_iqbal",
        "title": "Need someone to break my payments flow before it touches real money",
        "body": (
            "I have a small payments flow working and I am the only person who has tested "
            "it, which is the same as saying it is untested. Before anyone's actual rupees "
            "go through it I would like someone who enjoys breaking things to spend a few "
            "evenings trying.\n\n"
            "Paid, properly, out of my own pocket. I would much rather pay for this than "
            "find out the other way."
        ),
        "tags": ["Fintech", "Software", "testing", "payments"],
        "roles": ["qa-engineer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "serious",
        "city": "Hyderabad",
        "remote": True,
    },
    # ── Hardware & IoT ──────────────────────────────────────────────────────
    {
        "author": "rohan_mehta",
        "title": "A water-tank sensor under 500 rupees that doesn't need wifi on the roof",
        "body": (
            "Our building's pump runs dry twice a month because nobody can see the tank. "
            "Commercial sensors cost four thousand rupees and assume there is a wifi "
            "network up there, which there is not.\n\n"
            "I have a working ultrasonic prototype on an ESP32 talking over LoRa to a "
            "receiver in the stairwell. It has been up for six weeks. What it does not have "
            "is an enclosure that survives monsoon, or an app a watchman would actually "
            "use.\n\n"
            "Looking for someone who can design a printable waterproof housing, and "
            "separately someone who wants the mobile side. I will post you a board."
        ),
        "tags": ["Hardware & IoT", "Climate", "sensors", "lora"],
        "roles": ["hardware-engineer", "android-developer", "product-designer"],
        "custom_roles": ["Enclosure design"],
        "stage": "building",
        "commitment": "serious",
        "city": "Pune",
        "remote": True,
    },
    {
        "author": "rohan_mehta",
        "title": "Air quality monitor for a school, built by the students themselves",
        "body": (
            "A teacher friend asked whether her class could build something real. I think a "
            "PM2.5 monitor is close to perfect for this: cheap, visibly useful, and the "
            "data gets interesting the moment a bus goes past the window.\n\n"
            "I can do the electronics and run the soldering sessions. I need someone to turn "
            "it into a curriculum rather than a one-off workshop — four sessions, "
            "worksheets, something she could run again next year without me."
        ),
        "tags": ["Hardware & IoT", "Edtech", "Climate", "schools"],
        "roles": ["embedded-engineer", "writer", "mentor-advisor"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Pune",
        "remote": False,
    },
    {
        "author": "rohan_mehta",
        "title": "Anyone want to finish a MIDI controller with me",
        "body": (
            "Sixteen pads, four encoders, custom PCB, and it has been eighty per cent done "
            "in a drawer for eleven months. The firmware works. The case does not exist and "
            "I have lost the will to design one.\n\n"
            "Mostly looking for someone who will meet me on a Sunday and make me actually do "
            "it. Will share everything, no ownership nonsense."
        ),
        "tags": ["Hardware & IoT", "Content & Media", "music", "diy"],
        "roles": ["hardware-engineer", "musician"],
        "custom_roles": ["CAD / 3D printing"],
        "stage": "building",
        "commitment": "casual",
        "city": "Pune",
        "remote": False,
    },
    {
        "author": "rohan_mehta",
        "title": "Retrofit kit so an old sewing machine can count its own stitches",
        "body": (
            "I spoke to a tailoring unit where piece-rate pay gets argued about every week "
            "because nobody has a number. A hall-effect sensor on the wheel and a cheap "
            "display solves it for about three hundred rupees a machine.\n\n"
            "I am wary of building a surveillance device by accident, so I want someone who "
            "will think that through with me properly before any of it is installed anywhere."
        ),
        "tags": ["Hardware & IoT", "Social Impact", "manufacturing"],
        "roles": ["embedded-engineer", "business-analyst"],
        "custom_roles": ["Labour ethics"],
        "stage": "idea",
        "commitment": "casual",
        "city": "Pune",
        "remote": True,
    },
]

POSTS += [
    # ── Food & drink ────────────────────────────────────────────────────────
    {
        "author": "karthik_s",
        "title": (
            "Prep forecasting for a two-stove cloud kitchen, because my "
            "spreadsheet is lying to me"
        ),
        "body": (
            "Sixty orders a day, eleven items, and every Thursday I decide how much batter "
            "to soak based on vibes. When I am wrong in one direction I throw food away and "
            "when I am wrong in the other I cancel orders and take the rating hit.\n\n"
            "I have eighteen months of order history exported from the aggregator. It is "
            "messy but it is real. I think even something crude — last four Thursdays, "
            "weighted, adjusted for whether it rained — beats me guessing.\n\n"
            "Looking for someone who finds small real datasets more interesting than big "
            "clean ones. I cannot pay much but I can feed you for a year, and I mean that "
            "literally."
        ),
        "tags": ["Food & Drink", "AI & Data", "forecasting", "restaurants"],
        "roles": ["data-scientist", "backend-developer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Coimbatore",
        "remote": True,
    },
    {
        "author": "karthik_s",
        "title": "Tiffin subscription for office workers — launched, need help keeping it alive",
        "body": (
            "We run a weekly tiffin subscription for four offices nearby. Ninety subscribers, "
            "renewals collected over UPI, route planned by me on a scooter every morning.\n\n"
            "It works and it is growing faster than my admin. The two things breaking are "
            "pause-for-a-week requests, which currently arrive by phone call, and route "
            "planning, which currently lives in my head.\n\n"
            "Looking for someone who wants to build boring internal tools for a business "
            "that already has revenue. Happy to share a cut rather than pay a fee."
        ),
        "tags": ["Food & Drink", "E-commerce", "subscriptions", "operations"],
        "roles": ["full-stack-developer", "operations-lead"],
        "custom_roles": [],
        "stage": "launched",
        "commitment": "serious",
        "city": "Coimbatore",
        "remote": True,
    },
    {
        "author": "karthik_s",
        "title": "Does anyone want to write a proper food blog with me",
        "body": (
            "Not recipes. The economics of it — what an idli actually costs to make at "
            "scale, why the same dish is forty rupees in one place and a hundred and ten "
            "in another, what happens to the unsold stuff.\n\n"
            "I have the numbers and the access. I am a bad writer and I know it."
        ),
        "tags": ["Food & Drink", "Content & Media", "writing"],
        "roles": ["writer", "photographer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Coimbatore",
        "remote": True,
    },
    {
        "author": "karthik_s",
        "title": "Looking for a packaging designer who understands a 12-rupee budget",
        "body": (
            "Every designer I have spoken to has shown me beautiful work that would cost "
            "more per box than my entire margin on the meal inside it. One quoted me "
            "forty-one rupees a unit. I sell the meal for ninety.\n\n"
            "I need someone who finds the constraint interesting rather than insulting: "
            "one colour, a stock box I can buy locally in hundreds, a sticker, and it has "
            "to survive forty minutes on a scooter in the rain without the ink running.\n\n"
            "Small job, paid, and I will tell you honestly whether it moved anything — I "
            "track reorder rates weekly."
        ),
        "tags": ["Food & Drink", "Design", "packaging"],
        "roles": ["graphic-designer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Coimbatore",
        "remote": True,
    },
    # ── Climate ─────────────────────────────────────────────────────────────
    {
        "author": "imogen_clarke",
        "title": "Turn council air quality PDFs into one API nobody has to beg for",
        "body": (
            "I spent three years inside a council watching genuinely useful air quality "
            "data get published as a monthly PDF with the numbers in an image. There are "
            "about ninety councils doing the same thing in slightly different ways.\n\n"
            "I have working scrapers for eleven of them and a schema that holds up across "
            "all eleven. What I do not have is infrastructure that does not fall over, or "
            "any idea how to make this sustainable rather than a thing I maintain at "
            "midnight.\n\n"
            "Looking for someone who likes pipelines, and separately for someone who has "
            "run an open data project long enough to tell me how they usually die."
        ),
        "tags": ["Climate", "AI & Data", "open data", "civic tech"],
        "roles": ["devops-engineer", "backend-developer", "mentor-advisor"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "serious",
        "city": "Manchester",
        "remote": True,
    },
    {
        "author": "imogen_clarke",
        "title": "A repair-cafe map that is actually current",
        "body": (
            "There are four repair cafe directories for the north of England and all four "
            "list places that closed in 2021. The data problem is not collection, it is "
            "decay — nobody comes back to say they have stopped.\n\n"
            "I think the trick is making the listing expire unless someone confirms it, "
            "which is unfashionable and correct. Looking for a frontend person and ideally "
            "someone who runs one of these cafes and will tell me why I am wrong."
        ),
        "tags": ["Climate", "Campus & Civic", "repair", "maps"],
        "roles": ["frontend-developer", "community-manager"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Manchester",
        "remote": True,
    },
    {
        "author": "imogen_clarke",
        "title": "Household energy tracker for people on a prepayment meter",
        "body": (
            "Every energy app I have seen is built for someone on a monthly bill with a "
            "smart meter and an annual tariff. Prepayment is a completely different "
            "experience: you top up, you watch the number fall, you make decisions on "
            "Tuesday about Friday.\n\n"
            "I want to build for that, and I want to build it with people who are actually "
            "on one rather than for them. Looking for a designer who will come and do the "
            "interviews with me."
        ),
        "tags": ["Climate", "Social Impact", "energy", "household"],
        "roles": ["ux-designer", "user-researcher", "android-developer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Manchester",
        "remote": True,
    },
    {
        "author": "imogen_clarke",
        "title": "Quick one: anyone good at explaining charts to non-technical councillors?",
        "body": (
            "I have a dashboard that is correct and completely unreadable to the audience "
            "that needs it. Eleven filters, four tabs, and a councillor who has nine "
            "minutes before the next item on the agenda.\n\n"
            "I am fairly sure the fix is three sentences and one number per page rather "
            "than a better chart library, which means it is a writing job and not an "
            "engineering one. Every time I try to do it myself I end up explaining the "
            "methodology, which nobody asked for.\n\n"
            "Looking for someone who writes well about data and will cut most of what I "
            "give them."
        ),
        "tags": ["Climate", "Content & Media", "data viz"],
        "roles": ["writer", "user-researcher"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Manchester",
        "remote": True,
    },
    # ── Edtech ──────────────────────────────────────────────────────────────
    {
        "author": "tashi_dorji",
        "title": "Maths practice for a class where four students share one phone",
        "body": (
            "I taught a class last year where thirty-one students had access to seven "
            "phones between them, mostly their parents'. Every product I was shown "
            "assumed one device per child and a connection.\n\n"
            "What worked, by accident, was a paper worksheet I generated per student and "
            "photocopied. The generator was a hacked-together script. I want to make that "
            "a real thing: pick a topic and a difficulty, get thirty different worksheets "
            "and thirty answer keys, print, done. No student account, no login, no app.\n\n"
            "I know exactly what the maths should be. I need someone who can make a "
            "generator that produces questions a teacher would not be embarrassed by, and "
            "someone who can make the PDF look decent."
        ),
        "tags": ["Edtech", "Social Impact", "maths", "offline first", "schools"],
        "roles": ["backend-developer", "graphic-designer"],
        "custom_roles": ["Maths teacher"],
        "stage": "building",
        "commitment": "serious",
        "city": "Thimphu",
        "remote": True,
    },
    {
        "author": "tashi_dorji",
        "title": "A WhatsApp bot that sends one maths question a day, in Dzongkha and English",
        "body": (
            "Parents are on WhatsApp. Students are on WhatsApp. Nobody is on the app we "
            "would build.\n\n"
            "One question a day, reply with an answer, get told whether you are right and "
            "why. That is the whole product. I have written three hundred questions. "
            "Looking for someone who has built on the WhatsApp API and will tell me "
            "honestly whether this is viable or whether I am about to get the number "
            "banned."
        ),
        "tags": ["Edtech", "whatsapp", "bots", "regional languages"],
        "roles": ["backend-developer", "translator"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Thimphu",
        "remote": True,
    },
    {
        "author": "tashi_dorji",
        "title": "Looking for a teacher in another country to swap lesson plans with",
        "body": (
            "Not a startup, and I am not looking for anyone to build anything.\n\n"
            "I would just like one other secondary maths teacher somewhere else to swap "
            "materials with every month — here is what I taught, here is the worksheet, "
            "here is the bit where half the class went quiet and I had to start again. "
            "Nine years in and the only useful feedback I have ever had came from the one "
            "colleague who sat at the back of my room.\n\n"
            "I will go first and send you everything I have. Any country, any curriculum; "
            "the differences are the interesting part."
        ),
        "tags": ["Edtech", "teaching", "community"],
        "roles": ["mentor-advisor"],
        "custom_roles": ["Secondary teacher"],
        "stage": "idea",
        "commitment": "casual",
        "city": "Thimphu",
        "remote": True,
    },
    {
        "author": "tashi_dorji",
        "title": "Someone to help me turn nine years of worksheets into a book",
        "body": (
            "I have about four hundred worksheets in a cupboard, used and annotated and "
            "marked up with what went wrong. Several teachers have asked for copies.\n\n"
            "I do not know how to make a book. I do not know whether it should be free. I "
            "would like to talk to someone who has self-published something educational and "
            "did not lose money doing it."
        ),
        "tags": ["Edtech", "Content & Media", "publishing"],
        "roles": ["writer", "graphic-designer", "mentor-advisor"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Thimphu",
        "remote": True,
    },
    # ── Campus & civic ──────────────────────────────────────────────────────
    {
        "author": "ananya_bose",
        "title": "Making municipal tender documents searchable, which sounds dull and is not",
        "body": (
            "Every ward contract in this city is published, technically. It is published as "
            "a scanned PDF, named by date, in a folder you can only reach from a link on a "
            "page that moved last year.\n\n"
            "I have read about six hundred of these. There is a real story in them — the "
            "same four contractors, the same unfinished drains, every single monsoon. But "
            "nobody can read six hundred PDFs, so nobody does, so nothing happens.\n\n"
            "I want a searchable archive with the contractor, amount and ward pulled out. I "
            "can do the reading and the domain work. I need someone who can do the "
            "extraction, and I would love a journalist who would actually use it."
        ),
        "tags": ["Campus & Civic", "AI & Data", "Social Impact", "open data", "governance"],
        "roles": ["ml-engineer", "backend-developer", "writer"],
        "custom_roles": ["Journalist"],
        "stage": "building",
        "commitment": "serious",
        "city": "Kolkata",
        "remote": True,
    },
    {
        "author": "ananya_bose",
        "title": "A hostel complaint tracker that the warden also wants to use",
        "body": (
            "Every hostel complaint system I have seen was built by students, for students, "
            "and died because the warden kept using the register. If the person who resolves "
            "things is not on it, it is a suggestion box.\n\n"
            "So: design for the warden first. One screen, sorted by age, mark it done. "
            "Students get to see the queue, which is the entire point — most of the anger is "
            "about not knowing.\n\n"
            "Looking for one developer and one person who will sit with a warden for an hour "
            "and not argue with them."
        ),
        "tags": ["Campus & Civic", "Software", "campus", "hostels"],
        "roles": ["full-stack-developer", "user-researcher"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Kolkata",
        "remote": False,
    },
    {
        "author": "ananya_bose",
        "title": "Reading group on urban service delivery — want to turn it into a newsletter",
        "body": (
            "Eight of us have been meeting monthly for a year to read and argue about "
            "municipal service delivery. The notes are good. They are in a shared doc "
            "nobody outside the group will ever open.\n\n"
            "I would like to turn it into a short monthly newsletter, and for that I need "
            "someone who can edit ruthlessly, because academics cannot."
        ),
        "tags": ["Campus & Civic", "Content & Media", "newsletter", "policy"],
        "roles": ["writer", "content-creator"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Kolkata",
        "remote": True,
    },
    {
        "author": "ananya_bose",
        "title": "Bengali-first reading app for government forms",
        "body": (
            "A pension form is four pages of English legalese handed to someone who reads "
            "Bengali. The failure is not literacy, it is translation that nobody did.\n\n"
            "I want something where you photograph the form and get a plain-Bengali "
            "explanation of what each field wants. I have about sixty forms collected "
            "already. This needs someone who takes translation quality seriously, because a "
            "confident wrong answer here is worse than nothing at all."
        ),
        "tags": ["Campus & Civic", "Social Impact", "AI & Data", "accessibility"],
        "roles": ["ml-engineer", "translator", "ux-designer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Kolkata",
        "remote": True,
    },
    # ── Craft collective ────────────────────────────────────────────────────
    {
        "author": "harpreet_kaur",
        "title": "Eleven women do phulkari embroidery near Chandigarh. We need to be findable.",
        "body": (
            "We are good at what we do and invisible beyond about thirty kilometres. Every "
            "marketplace that has approached us wanted a margin that would leave the women "
            "earning less than they do now, so we said no, three times.\n\n"
            "I think the answer is our own shop, however small, plus somebody who "
            "understands how to get a page in front of people who care about this work. I "
            "can handle the making, the quality and the women. I cannot handle any of the "
            "rest.\n\n"
            "This is not a charity project and I would rather nobody treated it like one. "
            "There is real revenue and I will share it."
        ),
        "tags": ["Craft & Small Business", "E-commerce", "Social Impact", "textiles"],
        "roles": ["frontend-developer", "marketer", "photographer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Chandigarh",
        "remote": True,
    },
    {
        "author": "harpreet_kaur",
        "title": "Looking for someone to photograph textile work properly",
        "body": (
            "Embroidery photographs badly on a phone. The thread catches light in a way "
            "that needs someone who knows what they are doing, and right now our pictures "
            "make the work look flat and cheap, which it is not — people see the photo, "
            "decide it is machine-made, and never ask.\n\n"
            "About forty pieces, plus I would like some of the women at work rather than "
            "only the finished things. Two days in Chandigarh; I will arrange the travel, "
            "the stay, the food and all the pieces.\n\n"
            "Happy to pay properly for this. It is the single highest-value thing I could "
            "spend money on right now."
        ),
        "tags": ["Craft & Small Business", "Design", "photography"],
        "roles": ["photographer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Chandigarh",
        "remote": False,
    },
    {
        "author": "harpreet_kaur",
        "title": "How do eleven people split money fairly when the work is not equal?",
        "body": (
            "Some pieces take forty hours and some take six. Some women can only work "
            "evenings. We currently split by piece and it causes quiet resentment that "
            "nobody will say out loud.\n\n"
            "I am not looking for software. I am looking to talk to anyone who has run a "
            "cooperative or a collective and worked out something that held up over years."
        ),
        "tags": ["Craft & Small Business", "Social Impact", "cooperatives"],
        "roles": ["mentor-advisor", "finance-lead"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Chandigarh",
        "remote": True,
    },
]

POSTS += [
    # ── Health & fitness ────────────────────────────────────────────────────
    {
        "author": "sneha_kulkarni",
        "title": (
            "Physio exercises people will actually do, from someone who "
            "watches them not do them"
        ),
        "body": (
            "I hand out a paper sheet of six exercises. Patients do them for four days. I "
            "know this because I ask, and because they come back no better.\n\n"
            "The fitness apps are all built for people who already enjoy exercising. My "
            "patients are in pain, frightened of making it worse, and the sheet has a "
            "drawing of a man doing a movement they cannot do yet. The gap is not "
            "motivation, it is that nobody has designed for week one.\n\n"
            "I have the protocols, I see thirty people a week to test with, and I have no "
            "technical skill whatsoever. I would like to find one developer and one "
            "designer who want to build something small and genuinely useful rather than "
            "another streak counter."
        ),
        "tags": ["Health & Fitness", "Edtech", "physiotherapy", "rehab"],
        "roles": ["android-developer", "product-designer", "illustrator"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Nashik",
        "remote": True,
    },
    {
        "author": "sneha_kulkarni",
        "title": "Short videos of rehab exercises, in Marathi, free forever",
        "body": (
            "Forty videos, thirty seconds each, one exercise each, spoken in Marathi by "
            "someone who knows what they are talking about. There is nothing like this and "
            "every clinic in this district would send patients to it.\n\n"
            "I will do all the demonstrating and the script. I need someone with a camera "
            "and patience for about three weekends."
        ),
        "tags": ["Health & Fitness", "Content & Media", "regional languages"],
        "roles": ["video-editor", "photographer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Nashik",
        "remote": False,
    },
    {
        "author": "sneha_kulkarni",
        "title": "Appointment reminders that do not require me to own a computer",
        "body": (
            "I run my practice from a notebook and a phone. I lose maybe four appointments "
            "a week to people forgetting. Every clinic software I have been shown costs "
            "more per month than those four appointments are worth and wants me to learn a "
            "dashboard.\n\n"
            "If someone can tell me there is already a good answer to this, honestly, I will "
            "be delighted and will stop asking."
        ),
        "tags": ["Health & Fitness", "Software", "clinics", "small business"],
        "roles": ["open-to-anyone-not-sure-yet", "mentor-advisor"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Nashik",
        "remote": True,
    },
    # ── Climate / marine ────────────────────────────────────────────────────
    {
        "author": "meera_pillai",
        "title": "Six years of coastal water data that nobody outside my lab has ever seen",
        "body": (
            "We sample eleven points along the Kerala coast monthly and have done since "
            "2020. Salinity, dissolved oxygen, nitrates, the usual. It is good data, "
            "collected carefully, and it lives in spreadsheets on a shared drive and in two "
            "papers behind a paywall.\n\n"
            "Local fishing cooperatives ask me questions this data answers. I cannot hand "
            "them a spreadsheet. I want one page per sampling point with a chart and three "
            "sentences in Malayalam.\n\n"
            "I can clean the data and write the words. I need someone who can build "
            "something simple and host it for less than nothing, because there is no grant "
            "for this."
        ),
        "tags": ["Climate", "AI & Data", "Social Impact", "oceans", "open data"],
        "roles": ["frontend-developer", "data-scientist"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Kochi",
        "remote": True,
    },
    {
        "author": "meera_pillai",
        "title": (
            "A phone app for fishermen to log unusual catches — mostly I "
            "want to know if this is wanted"
        ),
        "body": (
            "Citizen science sounds lovely and usually means researchers extracting unpaid "
            "labour from people with better things to do. Before I build anything I want to "
            "know whether the people I would be asking actually want it, and what they would "
            "want back.\n\n"
            "So this is a post looking for a researcher or designer who has done honest "
            "participatory work, not a developer. Yet."
        ),
        "tags": ["Climate", "Social Impact", "citizen science"],
        "roles": ["user-researcher", "mentor-advisor"],
        "custom_roles": ["Participatory design"],
        "stage": "idea",
        "commitment": "casual",
        "city": "Kochi",
        "remote": True,
    },
    {
        "author": "meera_pillai",
        "title": "Illustrated field guide to Kerala estuary species, for school children",
        "body": (
            "There is no good one. The existing material is either an academic "
            "identification key that assumes a degree, or a laminated poster with four "
            "fish on it, three of which are not found here.\n\n"
            "I can write every entry and verify every identification, and I can get it "
            "into about sixty schools along the coast because I already visit them. I "
            "absolutely cannot draw — I have tried, and the result was unkind to the "
            "fish.\n\n"
            "Looking for an illustrator who would enjoy forty small watercolours of "
            "genuinely unglamorous estuary species. Mudskippers. Nothing charismatic."
        ),
        "tags": ["Climate", "Edtech", "illustration", "schools"],
        "roles": ["illustrator", "writer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Kochi",
        "remote": True,
    },
    # ── Games ───────────────────────────────────────────────────────────────
    {
        "author": "ishan_gupta",
        "title": "A small co-op game about running a tea stall. Need an artist.",
        "body": (
            "Two players, one stall, increasingly unreasonable orders. The loop works and "
            "it is funny — I have had six people play it and all six laughed at the right "
            "moment, which is more than my last three projects managed.\n\n"
            "It currently looks like grey boxes with text on them. I have shipped four "
            "games and I have learned the hard way that I cannot art my way out of a paper "
            "bag, and that shipping with my own art is how a good game dies at 200 "
            "downloads.\n\n"
            "Looking for one artist who wants a credit and a revenue split, not a fee. I "
            "will show you the numbers from the last two so you know what you are splitting."
        ),
        "tags": ["Games", "Design", "unity", "co-op"],
        "roles": ["illustrator", "animator"],
        "custom_roles": ["Pixel artist"],
        "stage": "building",
        "commitment": "serious",
        "city": "Noida",
        "remote": True,
    },
    {
        "author": "ishan_gupta",
        "title": "Game jam in Delhi NCR — anyone want to organise one with me",
        "body": (
            "Forty-eight hours, one weekend, a room, about thirty people. I have done this "
            "twice as a participant and both times the organising was the reason it was "
            "mediocre.\n\n"
            "I can find the venue and the people. I need someone who likes logistics and "
            "someone who can make a poster that does not look like a college fest."
        ),
        "tags": ["Games", "Campus & Civic", "events", "community"],
        "roles": ["community-manager", "graphic-designer", "project-manager"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Noida",
        "remote": False,
    },
    {
        "author": "ishan_gupta",
        "title": "Launched a tiny puzzle game, 80k downloads, zero idea what to do next",
        "body": (
            "It is out, people like it, the reviews are kind, and revenue is about enough "
            "for one nice dinner a month. I have no instinct for whether to build a sequel, "
            "add levels, port it, or move on entirely.\n\n"
            "Would really value half an hour with someone who has been through this on a "
            "small title. Not looking to hire anyone."
        ),
        "tags": ["Games", "growth", "mobile"],
        "roles": ["mentor-advisor", "growth-lead"],
        "custom_roles": [],
        "stage": "launched",
        "commitment": "casual",
        "city": "Noida",
        "remote": True,
    },
    # ── E-commerce ──────────────────────────────────────────────────────────
    {
        "author": "vikram_joshi",
        "title": "Returns are killing small D2C brands and nobody is building for it",
        "body": (
            "I have run fulfilment for about forty small brands. The ones that die mostly "
            "die of returns: 20-30% return rates, each one costing more than the margin on "
            "the sale, and no brand under a certain size has any visibility into which SKU "
            "or which size is doing it.\n\n"
            "The tooling that exists is built for companies doing ten thousand orders a day "
            "and priced accordingly. I want to build the version for someone doing fifty.\n\n"
            "I know this problem completely and I cannot write code. Looking for a technical "
            "co-founder, properly — not a contractor, someone who wants to own half of it."
        ),
        "tags": ["E-commerce", "Software", "logistics", "d2c"],
        "roles": ["co-founder", "backend-developer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Ahmedabad",
        "remote": True,
    },
    {
        "author": "vikram_joshi",
        "title": "Free teardown of your returns numbers if you will let me write about it",
        "body": (
            "Offering, not asking. If you run a small brand and you will share six months "
            "of returns data, I will go through it properly and tell you where the money is "
            "going. In exchange I want to write it up anonymously.\n\n"
            "I would like someone to help me turn these into readable posts, because my "
            "writing reads like a logistics manual."
        ),
        "tags": ["E-commerce", "Content & Media", "writing"],
        "roles": ["writer", "content-creator"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Ahmedabad",
        "remote": True,
    },
    {
        "author": "vikram_joshi",
        "title": "Looking for a finance person for a warehousing side business",
        "body": (
            "Small shared-warehouse idea in Ahmedabad for brands doing under two hundred "
            "orders a day. There are at least fifteen of them within an hour of me, all "
            "paying for space they half-use, and I can get the space.\n\n"
            "I understand the operations and I am confident about the demand because I "
            "have spent six years being the person those brands call. What I do not "
            "understand is the unit economics well enough to bet on — rent is fixed, "
            "revenue is not, and I cannot work out where the break-even actually sits.\n\n"
            "I would much rather find that out now than in month eight."
        ),
        "tags": ["E-commerce", "logistics", "warehousing"],
        "roles": ["finance-lead", "business-analyst"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Ahmedabad",
        "remote": False,
    },
    # ── Fintech / growth ────────────────────────────────────────────────────
    {
        "author": "daniel_osei",
        "title": "Savings app for market traders in Accra who already save, just not in a bank",
        "body": (
            "Susu collectors already exist and already work. People trust them, pay them, "
            "and get their money. Every fintech that has come at this has tried to replace "
            "the collector, and every one has failed, because the collector is the trust.\n\n"
            "So build for the collector. Give one person a tool that tracks forty "
            "customers, prints a receipt, and does not require them to be literate in "
            "English.\n\n"
            "I have spoken to eleven collectors. Nine said yes immediately. I need someone "
            "to build it and someone who will push back hard on whether this is "
            "exploitative, because I am too close to it."
        ),
        "tags": ["Fintech", "Social Impact", "savings", "africa"],
        "roles": ["android-developer", "ux-designer", "mentor-advisor"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Accra",
        "remote": True,
    },
    {
        "author": "daniel_osei",
        "title": "I will fix your onboarding funnel for free if the product is useful",
        "body": (
            "Offering. I took a lending app from four thousand to ninety thousand users and "
            "roughly all of it was fixing onboarding twice. It is the least glamorous and "
            "highest-leverage thing in most products.\n\n"
            "If you have something live with real users and a drop-off you cannot explain, "
            "send it to me. I want three of these, not thirty."
        ),
        "tags": ["Fintech", "growth", "onboarding"],
        "roles": ["growth-lead"],
        "custom_roles": [],
        "stage": "launched",
        "commitment": "casual",
        "city": "Accra",
        "remote": True,
    },
    {
        "author": "daniel_osei",
        "title": "Anyone want to co-write a newsletter about African fintech that isn't hype?",
        "body": (
            "Every newsletter in this space reads like a press release. I want the one that "
            "says which of these companies is actually making money and which is announcing "
            "partnerships.\n\n"
            "Fortnightly, two writers, so it survives one of us being busy. I can bring the "
            "operator view; I would like someone with a research habit."
        ),
        "tags": ["Fintech", "Content & Media", "newsletter"],
        "roles": ["writer", "business-analyst"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Accra",
        "remote": True,
    },
    # ── Social impact / community ───────────────────────────────────────────
    {
        "author": "olu_adeyemi",
        "title": "Our 2,000-person maker community runs on WhatsApp and it is at breaking point",
        "body": (
            "Three years in, nine groups, every one at the member limit, and finding "
            "anything said more than a day ago is impossible. People ask the same question "
            "weekly because the answer is unreachable.\n\n"
            "I have looked at every forum tool. They all assume people will leave WhatsApp, "
            "and they will not. What I think might work is something that lives alongside "
            "it — a searchable archive of the good answers, curated by a few of us, that we "
            "link back into the group.\n\n"
            "Looking for one developer. I will bring two thousand people on day one, which "
            "is not a thing most side projects get."
        ),
        "tags": ["Social Impact", "Software", "community", "whatsapp"],
        "roles": ["full-stack-developer", "community-manager"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "serious",
        "city": "Lagos",
        "remote": True,
    },
    {
        "author": "olu_adeyemi",
        "title": "Offering: I will find your first hundred users",
        "body": (
            "If you have built something and cannot get anyone to use it, that is usually "
            "not a product problem at a hundred users, it is a distribution problem, and "
            "distribution is a skill like any other.\n\n"
            "Happy to do this for two or three projects I believe in. I would want a small "
            "stake rather than a fee, and I will say no to anything I would not use."
        ),
        "tags": ["Social Impact", "growth", "community"],
        "roles": ["growth-lead", "marketer"],
        "custom_roles": [],
        "stage": "launched",
        "commitment": "casual",
        "city": "Lagos",
        "remote": True,
    },
    {
        "author": "olu_adeyemi",
        "title": (
            "A tool-lending library for the maker community — need "
            "someone who likes spreadsheets"
        ),
        "body": (
            "We have members with a lathe sitting idle and members who need a lathe for one "
            "afternoon. Matching them is currently me, in the evenings, badly.\n\n"
            "This needs almost no technology and a lot of thought about deposits, damage, "
            "and what happens when somebody does not bring it back. Looking for someone "
            "operationally minded more than technical."
        ),
        "tags": ["Social Impact", "Craft & Small Business", "community", "sharing"],
        "roles": ["operations-lead", "product-manager"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Lagos",
        "remote": True,
    },
    # ── Content & media ─────────────────────────────────────────────────────
    {
        "author": "zara_haq",
        "title": "Short documentary series about people who fix things for a living",
        "body": (
            "Phone repair, shoe repair, the man who rewinds motors. Eight episodes, eight "
            "minutes each, shot in Karachi.\n\n"
            "I can shoot it and I can cut it — that is my actual job. What I have never done "
            "is the part where it gets in front of anyone, or the part where it pays for "
            "itself. I have one episode finished and it is genuinely good; I would rather "
            "show it than describe it.\n\n"
            "Looking for a producer-ish person. Also open to being told this should just be "
            "on YouTube and I should stop overthinking it."
        ),
        "tags": ["Content & Media", "Craft & Small Business", "documentary", "video"],
        "roles": ["partnerships-lead", "project-manager", "marketer"],
        "custom_roles": ["Producer"],
        "stage": "building",
        "commitment": "serious",
        "city": "Karachi",
        "remote": True,
    },
    {
        "author": "zara_haq",
        "title": "Will edit your project video properly if the project is interesting",
        "body": (
            "I cut documentaries for a living and I am tired of brand work. If you have "
            "footage of something real and you have been putting off the edit because it "
            "frightens you, send it to me.\n\n"
            "Free for two projects. I want the portfolio piece and I want to work on "
            "something I care about for once."
        ),
        "tags": ["Content & Media", "video", "editing"],
        "roles": ["video-editor"],
        "custom_roles": [],
        "stage": "launched",
        "commitment": "casual",
        "city": "Karachi",
        "remote": True,
    },
    {
        "author": "zara_haq",
        "title": "Looking for a composer for eight minutes of music",
        "body": (
            "Documentary series, eight episodes, needs a theme and a handful of cues. I "
            "have been using library music and it makes everything sound like an insurance "
            "advert.\n\n"
            "Small budget, real credit, and I will cut to your music rather than asking you "
            "to score to my cut, which I am told is unusual and welcome."
        ),
        "tags": ["Content & Media", "music", "documentary"],
        "roles": ["musician"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Karachi",
        "remote": True,
    },
]


# ── The demo account's own three posts (§7.5) ────────────────────────────────
#
# Created every run regardless of `--posts`, because `demo@`'s profile tab being
# empty is the first thing a visitor sees after logging in with the published
# credentials. Kept separate from POSTS for exactly that reason: `--posts 5`
# must not be able to thin them away.

DEMO_POSTS = [
    {
        "title": "Looking for a frontend person for an internal tool nobody wants to build",
        "body": (
            "We have an ops team of six keeping a product alive with four spreadsheets and "
            "a WhatsApp group. I have mapped what the tool should do — it is not "
            "complicated, it is just nobody's priority — and I would like to build it as a "
            "side project with one other person.\n\n"
            "I will do the product work, the writing and the arguing with stakeholders. I "
            "need someone who can actually build the thing."
        ),
        "tags": ["Software", "Design", "internal tools"],
        "roles": ["frontend-developer", "product-designer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "title": "Running a small research study on how people pick side projects",
        "body": (
            "Twelve interviews so far. The pattern that keeps coming up is that people do "
            "not pick projects, they pick people — the idea is mostly an excuse to work with "
            "someone specific.\n\n"
            "I would like to do another twenty interviews and write it up properly. Looking "
            "for someone who has done qualitative research and will tell me where my "
            "questions are leading the witness."
        ),
        "tags": ["Design", "AI & Data", "research"],
        "roles": ["user-researcher", "writer"],
        "custom_roles": [],
        "stage": "building",
        "commitment": "casual",
        "city": "Bengaluru",
        "remote": True,
    },
    {
        "title": "A weekend workshop on writing a product spec that someone can build from",
        "body": (
            "I have read a lot of specs that were really wish lists. I would like to run a "
            "half-day thing — bring your idea, leave with something a developer could "
            "actually start on.\n\n"
            "Free, about fifteen people, Bengaluru. Looking for someone to co-run it, "
            "ideally an engineer who can say out loud which parts are unbuildable."
        ),
        "tags": ["Software", "Edtech", "workshops"],
        "roles": ["mentor-advisor", "backend-developer"],
        "custom_roles": [],
        "stage": "idea",
        "commitment": "casual",
        "city": "Bengaluru",
        "remote": False,
    },
]


# ── Comments ─────────────────────────────────────────────────────────────────
#
# Two pools, because the trade-off is real and worth stating.
#
# `TAILORED_COMMENTS` is keyed by post **title**, which is the same natural key
# §7.4 rule 3 already makes the seed depend on for idempotency — so it is one
# key, not two. Editing a title therefore drops that post back to the generic
# pool rather than crashing: deliberate, because a corpus that raises on a
# reworded title is a corpus nobody dares edit.
#
# `GENERIC_COMMENTS` is the fallback and every line in it is **field-agnostic on
# purpose**. A comment pool with any domain colour in it produces "I'd love to
# help with the crochet!" under a fintech post, which is worse than no comment
# at all — it is the uncanny-valley version of a community.

TAILORED_COMMENTS = {
    "I run a crochet business and I need an actual shop, not an Instagram DM": [
        "The lost-order-in-a-message-folder thing is so common and so fixable. "
        "What's your rough product count — ten, fifty, two hundred?",
        "Honestly you may not need anyone to build this from scratch. Happy to walk "
        "you through the two or three off-the-shelf options first and only build if "
        "none of them fit. Free either way.",
        "Following. I'm in a similar spot with pottery and I'd rather solve it once "
        "with someone than badly twice on my own.",
    ],
    "Open annotation tool for Indian-language text that doesn't assume English": [
        "The conjunct rendering problem is the whole thing and most people don't find "
        "out until they're three weeks in. Which stack were you thinking for the "
        "editor itself?",
        "I'd use this tomorrow. We abandoned a labelling project last year basically "
        "for the reason you've described.",
    ],
    "A water-tank sensor under 500 rupees that doesn't need wifi on the roof": [
        "Six weeks uptime on a rooftop through actual weather is more than most "
        "prototypes manage, so you're further along than the post suggests.",
        "Interested in the housing side. Do you have the board dimensions anywhere? "
        "I can get something printed and tested within a week.",
        "What happens when the receiver loses the link — does it hold the last reading "
        "or go blank? That's the bit a watchman will judge it on.",
    ],
    "Prep forecasting for a two-stove cloud kitchen, because my spreadsheet is lying to me": [
        "Eighteen months of real orders from one kitchen is a better dataset than most "
        "people get to work with. I'd start with a plain weighted average and only get "
        "clever if it isn't good enough.",
        "The rain variable is doing a lot of work here and it's genuinely available for "
        "free. Would be curious how much of the variance it explains on its own.",
    ],
    "Maths practice for a class where four students share one phone": [
        "The decision to generate paper rather than an app is the strongest thing in "
        "this post and I'd protect it against everyone who tells you to build an app.",
        "I can do the PDF layout side. Thirty worksheets and thirty keys per run is "
        "straightforward; making them not look like a tax form is the actual work.",
    ],
    "Making municipal tender documents searchable, which sounds dull and is not": [
        "Six hundred PDFs read by hand is the kind of groundwork that makes the "
        "extraction tractable later. Have you kept notes on the format variations?",
        "Scanned-PDF extraction at this quality level is mostly a preprocessing "
        "problem. Happy to look at a sample of ten and tell you honestly how bad it is.",
    ],
    "Eleven women do phulkari embroidery near Chandigarh. We need to be findable.": [
        "Saying no to three marketplaces over margin is the right call and most people "
        "don't have the nerve for it.",
        "I've done fulfilment for small brands and the thing that will bite you first "
        "is shipping costs on single items. Worth sorting before the shop exists.",
    ],
    "Physio exercises people will actually do, from someone who watches them not do them": [
        "\"Nobody has designed for week one\" is the clearest problem statement I've "
        "read on here.",
        "Thirty patients a week to test with is worth more than the engineering. Most "
        "health apps are built with zero access to actual patients.",
        "Interested. Would want to sit in on a few sessions before designing anything, "
        "if that's possible.",
    ],
    "Six years of coastal water data that nobody outside my lab has ever seen": [
        "One page per sampling point with a chart and three sentences is a weekend of "
        "work and it's also exactly the right scope. Please don't let anyone talk you "
        "into a dashboard.",
        "Hosting this for free is entirely doable if the data updates monthly rather "
        "than live. Happy to set it up and hand you the keys.",
    ],
    "A small co-op game about running a tea stall. Need an artist.": [
        "Six for six on the laugh is a real signal. I'd ship the grey boxes to twenty "
        "more people before committing an artist to it, honestly.",
        "Interested in the art. What's the resolution and roughly how many assets are "
        "we talking?",
    ],
    "Returns are killing small D2C brands and nobody is building for it": [
        "Having run ops for forty brands is the moat here, not the software. Whoever "
        "joins you is getting the easy half.",
        "Would want to understand how you'd get the returns data in the first place — "
        "is that an integration per courier?",
    ],
    "Savings app for market traders in Accra who already save, just not in a bank": [
        "\"Build for the collector\" is the insight. Every version of this that tried "
        "to disintermediate trust has failed for the same reason.",
        "I'll happily be the person who pushes back on the exploitation question. "
        "Message me.",
    ],
    "Our 2,000-person maker community runs on WhatsApp and it is at breaking point": [
        "Two thousand people on day one changes what's worth building. Most of us "
        "would kill for that distribution.",
        "The alongside-rather-than-instead-of framing is right. Every community that "
        "has tried to migrate off WhatsApp has lost half its people doing it.",
    ],
    "Short documentary series about people who fix things for a living": [
        "Please link the finished episode. Hard to react to a description of a film.",
        "The repair-economy angle is having a moment, which is either very good timing "
        "or very crowded. Worth checking what else exists before episode three.",
    ],
    "Chit-fund bookkeeping, but not in a pencil notebook": [
        "The printed page that anyone can check is the part that makes this work. "
        "Digital-only would break the trust the whole thing runs on.",
        "I've built Telugu interfaces before and the font and line-height choices "
        "matter more than you'd expect. Happy to share what we learned.",
    ],
    "Turn council air quality PDFs into one API nobody has to beg for": [
        "Eleven councils with one schema holding up across all of them is the hard part "
        "done. The infrastructure is a solved problem by comparison.",
        "Open data projects usually die when the maintainer gets a new job. Worth "
        "designing for that from the start rather than hoping.",
    ],
}

GENERIC_COMMENTS = [
    "Following this one. Interested to see where it goes.",
    "This is a real problem and I've not seen anyone solve it well.",
    "What does the first version look like? I find it easier to react to something "
    "small and specific.",
    "How are you thinking about the first ten users? That's usually where these live "
    "or die.",
    "I'd be up for a call about this. No agenda, just interested.",
    "Have you looked at what already exists here? Not a criticism — genuinely might "
    "save you three months.",
    "The scope feels right. The failure mode would be adding a second feature before "
    "the first one works.",
    "I don't have the skills you're asking for but I'd use this.",
    "What's the thing you're least sure about? That's usually the more useful "
    "conversation.",
    "Saved this. I know two people who'd be a good fit; will point them here.",
    "Strongly agree with the framing. Most attempts at this start from the wrong end.",
    "How much time a week are you expecting from whoever joins? Worth saying up front.",
    "This is the second post I've seen this month about roughly this problem, which is "
    "usually a good sign.",
    "I'd want to understand the money side before committing, but the idea is sound.",
    "Could you say more about what you've already tried? The dead ends are often the "
    "most useful part.",
    "Happy to review whatever you build, if that's useful. I like being the person who "
    "finds the awkward edge cases.",
    "The constraint you've described is the interesting part of this, not a limitation.",
    "I've tried something adjacent and failed at it. Happy to tell you how, if you want "
    "to skip that bit.",
    "Any chance of a screenshot or a sketch? Easier to react to.",
    "This reads like you've actually sat with the problem rather than imagined it.",
    "Count me interested. I can commit evenings, not weekends.",
    "What would make this a no for you? Trying to work out if I'd be useful.",
    "The honest answer might be that this doesn't need to be software at all, and I "
    "mean that as a compliment to the thinking.",
    "I'd start even smaller than this. One user, by hand, for a month.",
    "Bookmarking. Not the right person but this deserves to exist.",
    "Would you be open to doing this as a two-week experiment rather than a project? "
    "Lower stakes for everyone.",
    "Replying so I remember to come back to this properly.",
    "What's the budget situation? Not asking to be difficult, just so expectations "
    "match.",
    "I like that you've said what you can't do. Most posts here don't.",
    "There's a version of this that's a spreadsheet and a WhatsApp group, and that "
    "version would tell you a lot before anyone writes code.",
    "Genuinely good idea. My only worry is how you keep it current after month three.",
    "Sent you a message.",
    "The second paragraph is the actual product. Might be worth leading with it.",
    "I've got some domain knowledge here if you want a sounding board. No charge, "
    "obviously.",
    "How would you know if it was working? Worth deciding before you build.",
    "This is adjacent to something I'm doing. Might make sense to talk even if we don't "
    "end up working together.",
    "Love it. One question: who is the first person who pays, and what do they pay for?",
    "Have you tested the assumption in paragraph one? Everything else rests on it.",
    "Would be happy to help with a small part of this rather than the whole thing, if "
    "that's useful to you.",
    "Noted and following. Good luck with it.",
]


# ── Follow notes (spec §2.2 — the optional note on a follow) ────────────────
#
# The note is one of the product's better small ideas and it only reads that way
# if the notes sound like people. These are deliberately specific.

FOLLOW_NOTES = [
    "I'd want the backend role if you're still looking.",
    "Following because of the water tank post. Let me know if you need testers.",
    "We're working on similar problems from opposite ends.",
    "Saw your profile from a comment thread. Good taste in problems.",
    "I can help with the design side whenever you're ready for it.",
    "Here for the crochet shop. Rooting for it.",
    "Mostly following to steal your ideas, respectfully.",
    "Happy to be a sounding board any time.",
    "",
    "",
    "",
    "Your post about returns was the most useful thing I read this week.",
    "",
    "Would love to work together on something eventually.",
    "",
]


# ── The demo account's two conversations (§7.5) ─────────────────────────────
#
# `with_user` is a username from PEOPLE. `origin_post_title` ties the thread to
# the idea it started about, which is the GAP 11 / M5 context strip — a thread
# with no origin renders a header that cannot answer "why is this person
# messaging me", so both demo threads have one.
#
# The last message in each thread is **from the other person**, so both
# conversations land in `demo@`'s inbox unread. That is the §7.5 requirement
# ("2 conversations with unread messages") and it only holds if the final
# sender is not the demo account — easy to break by adding a polite sign-off.

DEMO_CONVERSATIONS = [
    {
        "with_user": "priya_ramesh",
        "origin_post_title": (
            "I run a crochet business and I need an actual shop, not an Instagram DM"
        ),
        "messages": [
            ("demo", "Hi Priya — saw your post about the shop. How many products are we "
                     "talking about, roughly?"),
            ("other", "Hello! About 30 at any time, but only 8 or 9 are repeat sellers. "
                      "The rest are one-offs."),
            ("demo", "That's small enough that you almost certainly don't need anything "
                     "custom built. Can I ask what you're paying for hosting right now?"),
            ("other", "Nothing. There is no website at all, that is the whole problem 😅"),
            ("other", "Would you have 20 minutes this week? I can show you the notebook "
                      "and you will understand the problem immediately."),
        ],
    },
    {
        "with_user": "nandini_rao",
        "origin_post_title": (
            "Looking for a frontend person for an internal tool nobody wants to build"
        ),
        "messages": [
            ("other", "Hi — I'm not a frontend dev but I do design, and the ops-tool "
                      "problem you described is one I've worked on twice."),
            ("demo", "That's genuinely more useful than another developer at this stage. "
                     "What went wrong the two previous times?"),
            ("other", "Both times we designed for the manager rather than the six people "
                      "actually doing the work. They kept the spreadsheet."),
            ("other", "I've got a rough wireframe from one of those projects I can share "
                      "if it helps. Shall I send it over?"),
        ],
    },
]


# ── Two open reports, so the moderation queue isn't empty (§7.5) ────────────
#
# Deliberately mundane. A demo moderation queue full of lurid abuse examples is
# both unpleasant to look at in a portfolio piece and unrepresentative: the real
# queue is mostly ambiguous spam. `target` is "post" or "comment".

DEMO_REPORTS = [
    {
        "target": "post",
        "reason": "spam",
        "details": (
            "Third post this week from this account that reads like an advert for a paid "
            "course rather than a project looking for collaborators. Not abusive, just "
            "not what the feed is for."
        ),
    },
    {
        "target": "comment",
        "reason": "inappropriate",
        "details": (
            "This comment is dismissive of the author in a way that will put people off "
            "posting. Borderline rather than clear-cut — flagging it for a second opinion "
            "rather than because I'm sure."
        ),
    },
]
