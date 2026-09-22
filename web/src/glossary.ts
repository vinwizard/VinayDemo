// Plain-English definitions of every term this product invented, in one place. The report shows
// each one behind a dotted underline (or a small ⓘ) wherever the term appears, so a reader who has
// never seen the product is never left guessing. Ordinary words get no entry.
export const GLOSSARY = {
  brand_question: {
    term: "Brand question",
    def: "A question we asked an AI that names the company but never names any claim, such as \"What is "
      + "this company known for?\". Whatever the AI says the company is good at, it said on its own. "
      + "These answers drive the headline number.",
  },
  buyer_question: {
    term: "Buyer question",
    def: "A question a buyer might ask an AI without naming the company, such as \"What tools help with X?\". "
      + "It measures whether the AI brings the company up by itself. These answers drive buyer visibility.",
  },
  untapped_potential: {
    term: "Untapped potential",
    def: "The share of what the company wants to be known for (or, if nothing was weighted, of what its "
      + "site says) that AI does not yet say when asked about it. 100 minus the score shown beside it. "
      + "Lower is better.",
  },
  claim_echo: {
    term: "Claim echo",
    def: "How much of what the company's own website says the AI repeats supportively when asked about "
      + "the company. Claims stated on more pages count for more. Used as the score when nothing has been weighted.",
  },
  alignment: {
    term: "Alignment",
    def: "How much of what the company wants to be known for the AI says supportively when asked about "
      + "the company, weighted by how much each claim matters to it. Used as the score once claims are weighted.",
  },
  buyer_visibility: {
    term: "Buyer visibility",
    def: "Out of 100: how often the company came up when a buyer asked an AI without naming it. A mention "
      + "scores half, a recommendation full. A separate measure: it does not move the headline.",
  },
  tries: {
    term: "Tries and range",
    def: "An AI gives a different answer each time it is asked, so each buyer question is asked several "
      + "times, each in a fresh conversation. Buyer visibility is the average of those tries; the range "
      + "is the lowest and highest single try.",
  },
  confidence_interval: {
    term: "Confidence interval",
    def: "How far a number could move if we asked again. We re-draw the same answers 2,000 times at "
      + "random (a bootstrap) and keep the middle 95% of the results: if we repeated the whole run, the "
      + "number would very likely land in that range, shown as low–high beside it.",
  },
  significant_gap: {
    term: "Real gap",
    def: "A gap we are 95% confident is not luck. We re-draw both sides' answers 2,000 times; if the "
      + "gap never crosses zero in the middle 95% of those draws, it is real. If it does, the two "
      + "numbers cannot be told apart with this many answers. With fewer than 5 questions a side, or a "
      + "side whose answers never varied, we do not call it at all.",
  },
  low_confidence: {
    term: "Low confidence",
    def: "For each set of buyer questions we also ask the AI to name the leading tools in that category. "
      + "If it names too few, or does not name the company among them, the buyer visibility may say more "
      + "about what the AI knows than about how buyers see the company, so we flag it rather than trust it.",
  },
  core_category: {
    term: "Core category",
    def: "The kind of product the company is, in a buyer's words (for example \"project management "
      + "software\"), as its own homepage puts it. Half of the buyer questions ask about it: where "
      + "you aim to be.",
  },
  where_placed: {
    term: "Where AI places you",
    def: "The category AI already links the company to: of everything the brand answers said about it, "
      + "the one they endorsed most often. Half of the buyer questions ask about this category, with no "
      + "brand named, to see whether AI also brings the company up there on its own.",
  },
  real_demand: {
    term: "Real demand",
    def: "A buyer question taken from what people actually search, not written by AI: Google's "
      + "autocomplete suggestions for the category (and Reddit threads, when Reddit allows it). Similar "
      + "searches are grouped by meaning and the biggest groups are asked first. It shows the questions "
      + "are real, not how many people search them.",
  },
  where_aiming: {
    term: "Where you aim to be",
    def: "The category the company's own homepage says it is in (the core category). Half of the buyer "
      + "questions ask about it. The gap between this and where AI places you is how far AI's picture "
      + "of the company is from the one it is aiming for.",
  },
  endorsed: {
    term: "Mentioned vs endorsed",
    def: "Mentioned: the AI raised the claim at all. Endorsed: it raised it in the company's favour. "
      + "Each one is backed by a word-for-word quote from the answer. Only endorsements count toward the score.",
  },
  share_of_voice: {
    term: "Share of voice",
    def: "Out of the buyer questions that count, how many answers recommended the company compared with "
      + "the products the AI recommended most often instead.",
  },
  rival_only: {
    term: "Sites that skip you",
    def: "Sites the AI cited in a buyer answer that named a rival but never mentioned the company. The AI "
      + "read these pages when it picked your rivals, so they are the review sites, lists and articles "
      + "to get onto. Ranked by how many buyer answers cited them, then by how many rivals sat beside them.",
  },
  source_type: {
    term: "Site type",
    def: "What kind of site a citation points at: the company's own site, a rival's own site, a review "
      + "site (G2, Capterra…), a community (Reddit, forums), media or a blog, or other. Sorted from a "
      + "short list of well-known sites plus the address itself, so an unfamiliar site shows as other.",
  },
  citation_map: {
    term: "Citation map",
    def: "Every brand named in a buyer answer, joined to each site that answer cited. A site joined to "
      + "several rivals and never to the company is where the AI learns about the category without "
      + "learning about the company.",
  },
  landed: {
    term: "Landed",
    def: "A claim the company wants to be known for, and the AI already says it. This is working.",
  },
  lost_claim: {
    term: "Claim to win back",
    def: "The company's site clearly says this, but the AI does not repeat it yet. The message is there; "
      + "the AI is not picking it up.",
  },
  unstated_intent: {
    term: "Claim to amplify",
    def: "The company wants to be known for this, but few of its own pages say it, so the AI has little "
      + "to repeat. Saying it on more pages is the first step.",
  },
  contested: {
    term: "Claim to correct",
    def: "The AI talks about this claim but tells a different story from the company's, often the "
      + "opposite. Room to set the record straight.",
  },
  imposed: {
    term: "Identity to shape",
    def: "Something the AI already links the company to, even though the company never claimed it. "
      + "Adopt it or reframe it.",
  },
  unprioritised: {
    term: "Unweighted echo",
    def: "The company's site says this and the AI repeats it, but the company did not mark it as "
      + "something it wants to be known for. Not a problem, just not a priority yet.",
  },
  crawlers: {
    term: "AI crawlers",
    def: "The bots AI companies send to read the web: GPTBot, OAI-SearchBot and ChatGPT-User (OpenAI), "
      + "PerplexityBot, ClaudeBot (Anthropic) and Google-Extended (Google's AI switch). A site's robots.txt "
      + "file can turn any of them away, and then that AI cannot read the page.",
  },
  raw_text: {
    term: "Readable without JavaScript",
    def: "Most AI crawlers download a page's HTML and never run its JavaScript, so words that appear only "
      + "after scripts run are invisible to them. We read your pages the same way.",
  },
  markup: {
    term: "Structured data",
    def: "Machine-readable labels (schema.org) inside a page that say what it is, such as a company, a "
      + "product or an FAQ, so AI does not have to guess.",
  },
  headings: {
    term: "Clear headings",
    def: "One main heading (H1) plus subheadings that split the page into passages. AI answers are built "
      + "from passages; a subheading phrased as a buyer's question is a bonus, never a requirement.",
  },
  speed: {
    term: "Speed",
    def: "How long the page took to arrive, measured once from our server. Crawlers work to a time limit "
      + "and skip pages that are slow. One reading, not an average.",
  },
  llms_txt: {
    term: "llms.txt",
    def: "A plain-text file at the root of a site that points AI tools to its important pages. A new, "
      + "optional convention: few AI tools read it yet.",
  },
  no_js: {
    term: "Script-only pages",
    def: "Pages that show almost no text until JavaScript runs. An AI crawler that skips scripts sees "
      + "them as nearly empty.",
  },
  fact_sources: {
    term: "Where AI gets its facts",
    def: "Besides your own site, AI models learn about companies from reference sites, above all "
      + "Wikipedia and Wikidata. A company with no Wikidata entry is often one AI simply does not know.",
  },
  fan_out: {
    term: "Fan-out search",
    def: "Before an AI with web search answers a question, it rewrites it into a few short web searches "
      + "of its own and reads the pages they return. Those searches are its fan-out. A site the searches "
      + "never turn up is rarely the one the AI cites.",
  },
  retrieval_score: {
    term: "Retrieval score",
    def: "A simulation of what an AI search reads first. We split your pages, and the pages the AI "
      + "cited, into short passages and score how closely each one matches the buyer question and the "
      + "AI's own searches for it, from 0 (unrelated) to 1 (the same meaning). The AI tends to read "
      + "and cite the closest passages, so a higher score makes a citation likelier, never certain.",
  },
  positioning_map: {
    term: "Positioning map",
    def: "A picture of how alike things sound, not a measurement. We turn what AI says about you, what "
      + "it says about each rival and what your own site says into numbers by meaning, then flatten "
      + "them onto two axes. Dots close together were described in similar words; the arrow runs from "
      + "where AI places you to where you want to be (the claims you weighted) or, until you weight "
      + "any, to where your site aims.",
  },
} satisfies Record<string, { term: string; def: string }>;

export type TermKey = keyof typeof GLOSSARY;
