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
  low_confidence: {
    term: "Low confidence",
    def: "We also ask the AI to name the leading tools in the company's category. If it does not name "
      + "the company there either, a low buyer visibility may say more about what the AI knows than "
      + "about how buyers see the company, so we flag it rather than trust it.",
  },
  core_category: {
    term: "Core category",
    def: "The kind of product the company is, in a buyer's words (for example \"project management "
      + "software\"). At least half of the buyer questions ask about it, and the check behind low "
      + "confidence uses it.",
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
} satisfies Record<string, { term: string; def: string }>;

export type TermKey = keyof typeof GLOSSARY;
