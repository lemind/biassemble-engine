# Curse of Knowledge

## Definition
The difficulty experienced by people who have knowledge or expertise in a domain when trying to understand or communicate with those who lack that knowledge. Experts cannot easily remember what it was like not to know something, and they unconsciously assume that others share their background knowledge. The curse of knowledge leads to communication failures, poor teaching, and frustrated collaboration between experts and novices. It was named and described in a 1989 Journal of Political Economy paper and made famous by Chip and Dan Heath in "Made to Stick."

## Examples
In technology, senior engineers write documentation that assumes readers understand jargon, dependencies, and architectural concepts that are second-nature to the author but opaque to a newcomer. The documentation is accurate but unusable by its intended audience.

In finance, financial advisors describe investment products using technical terms (Sharpe ratio, duration, convexity) to clients without recognizing that the client does not share this vocabulary. They cannot remember the experience of not knowing these concepts.

In medicine, physicians communicate diagnoses and treatment plans in clinical language that patients cannot interpret, leading to non-compliance and adverse outcomes caused by misunderstanding rather than bad decisions.

In education, expert instructors skip steps in explanations that feel obvious to them but are missing links for students. They underestimate how much background knowledge a derivation requires.

In product design, engineers build interfaces that make sense given their deep knowledge of the system's internals, producing unintuitive experiences for users who see only the surface.

## Indicators
- Explains something accurately but in a way the audience cannot follow, without noticing the gap
- Gets frustrated when someone needs a more basic explanation of something that feels obvious
- Cannot understand why steps that seem self-evident would need to be spelled out explicitly
- Writes instructions that skip foundational concepts, not realizing those concepts were ever difficult to learn
- Gives feedback or directions without explaining background terms or context that the audience does not share

## False Positives
- Calibrating communication to an expert audience when the audience actually is expert is not the curse of knowledge — it is appropriate audience awareness
- Brevity in expert-to-expert communication that relies on shared vocabulary is efficient, not cursed
- A teacher who accurately knows their students' level and pitches explanation accordingly has overcome the curse of knowledge rather than exhibiting it

## Related Biases
Dunning-Kruger Effect, Authority Bias, Halo Effect, Overconfidence Bias

## Story Patterns

[Technical] I wrote the onboarding docs for our API last year. New developers keep asking the same questions in the support channel and it's genuinely confusing to me. The answers are right there in the docs. My teammate suggested I ask a developer who's never used an API to read through them. I was skeptical but I did it. She got stuck on step two. I'd assumed everyone knew what an endpoint was.

[Educational] I've been teaching introductory economics for twelve years. My lecture notes feel comprehensive to me. After the midterm, almost a third of the class got the budget constraint question wrong. I went back and looked at my notes. I had assumed students understood that income was held constant as you shift along the line. I never said that explicitly. It seemed too obvious to state.

[Management] I briefed my new hire on the project this week. I thought I gave a thorough handoff. She came back three days later with questions that made me realize she hadn't understood the basic context of what we're trying to accomplish. I'd jumped straight to the task details without explaining why we were doing any of it. That why is so obvious to me I didn't think to say it.

[Medical] I explained the treatment protocol to my patient in detail. He nodded throughout. He came back at his follow-up having done almost none of it. When I asked what had happened, he said he hadn't understood the order in which to take the medications or why timing mattered. I'd explained the timing in what felt like plain terms. I hadn't explained why it mattered at all. I thought that was self-evident.

[Financial] I presented the portfolio rebalancing strategy to my client. She seemed engaged. At our next meeting she'd done nothing with the recommendation and said she didn't understand what she was supposed to actually do. I'd explained the theory clearly — I'd used "rebalance," "allocation," "asset class." She didn't know what any of those words specifically meant in terms of what to do with her phone and her brokerage account. I'd described the logic and skipped the actual mechanics.

[Legal] I wrote a contract addendum and emailed it to my client with a short note saying to sign by end of week. He called to ask what he was signing. I'd written it in normal contractual language — I thought the operative clause was clear. It wasn't clear to him at all. He didn't know what "in perpetuity" meant. He didn't understand what rights he was conveying. I'd sent the document as if reading it would be as obvious as writing it had been.

[Consumer] I set up the smart home system for my parents while I was visiting. I showed them everything carefully. A week later they called because they couldn't change the thermostat. I walked them through it over the phone and what I thought was obvious — tap the circle, swipe up, confirm — turned out to be a multi-step process that made no sense to them. I'd explained it while doing it, not while forgetting how to do it. Those are different experiences.

[Social] My partner asked me to explain why I got frustrated in the conversation with my brother over dinner. I started explaining and halfway through I said "you know how he does that thing." She said she didn't know. I realized I'd been referencing ten years of family dynamics that felt obvious to me but that I hadn't described. Every sentence I said assumed she already knew the backstory.

[Family] I was helping my teenager with her college application essays. I gave feedback like "be more specific" and "this section needs stronger analysis." She came back with revisions that hadn't changed in the ways I meant. She told me she didn't understand what I was asking for. I'd been writing feedback the way an editor would — I'd assumed she had access to the mental category of "stronger analytical move" that I could picture clearly but had never described.

[Technical] My code review comments are concise — I try to be efficient. A junior developer on my team asked me why I'd left a comment saying "consider the edge case here." She didn't know what edge case I was seeing. I'd written the comment because the edge case was obvious to me once I'd seen a similar failure in production two years ago. I had never described the edge case itself because it was so present to my thinking.

[Educational] I assigned a research paper with a rubric. Several students received low marks and a few came to office hours upset. Looking at the rubric criteria — "demonstrates critical engagement with secondary literature" — I realized I had never defined what critical engagement meant in practice. I know exactly what it looks like when I see it. I'd assumed they'd know it when they were doing it.

[Management] I asked my team to prepare a brief for the executive team. The briefs came back at eight to ten pages. I'd wanted one page. I said "brief" because to me a brief means one page with clear takeaways. I'd never said that explicitly. In their context, a thorough brief was the right thing to produce. I'd communicated a format that was entirely in my head.

[Medical] A patient told me he'd stopped taking the medication because it was "making things worse." When I asked what he meant, he described symptoms that are a normal part of how this medication works in the first few weeks. I'd explained the medication but I hadn't explained that there would be an adjustment period that looked like things getting worse before they got better. That adjustment phase is so familiar to me I didn't think to describe it.

[Financial] I recommended a tax strategy to my client and she implemented it incorrectly, creating a problem we had to untangle. When I looked at my original written advice, I had described the strategy clearly from a technical standpoint. I hadn't walked through the steps in sequence as if someone were doing it for the first time. I'd described the destination, not the route.

[Technical] The deployment runbook I wrote works perfectly if you already understand the infrastructure. Two new DevOps engineers tried to follow it last month and got stuck at step four. They'd never seen the particular pattern I used for service orchestration. The step says "configure the health check." I know exactly what that means — I designed the system. The runbook doesn't say what it means or why it's necessary.

[Educational] I gave a guest lecture on my research area to undergraduates. The feedback forms said it was hard to follow. I thought I'd kept it accessible. When I looked at my slides afterward I saw I'd used fourteen terms that are part of my everyday vocabulary but are specialist jargon. I'd said things like "endogenous variation" without pausing. It's so embedded in my thinking that I stopped noticing when I use it.

[Management] I asked my marketing team to give the quarterly results a "sharper narrative." I thought I was being helpful. Three days later I looked at the draft and they'd added more content rather than sharpening the argument. They hadn't understood what I meant. What "sharper narrative" looks like is completely clear in my head. I'd never been able to describe it out loud in a way that transferred the mental image.

[Legal] I told the paralegal to "clean up the discovery responses before filing." She cleaned up the formatting and fixed the typos. I'd meant she should review the substantive accuracy of every response against the documents. "Clean up" means something specific to me — it's a phrase I use internally to mean a substantive quality pass. To someone who hasn't been through dozens of discovery cycles, "clean up" meant formatting.

[Consumer] I set up my father's new smartphone. I installed all the apps he'd need and showed him how everything worked. Two days later he called and said he couldn't find his photos. I'd shown him the photo app once, quickly, because to me the navigation is intuitive. It's intuitive because I've used this operating system for five years. He's using it for the first time. "Just tap the icon" doesn't help if you don't yet have a model of what the screen is showing you.

[Technical] I presented the system architecture to the non-technical stakeholders in the quarterly review. I thought I'd simplified it well — I'd removed most of the technical detail. Afterward the VP of Product said she still didn't understand what the system does. I'd simplified the implementation details but I hadn't explained the system's purpose and behavior from the outside. The inside view was so present to me that I'd oriented the whole explanation from it.

[Educational] I gave written feedback on my graduate student's chapter draft. He came to my office to discuss it and I realized he'd misunderstood most of my comments. I use a shorthand in my annotations — phrases like "trace the causal mechanism" — that means something precise to me from years of reading in this field. To him, these were ambiguous directives. I hadn't explained what I meant when I first introduced my annotation style.

[Social] I was trying to explain to my friend why I was upset about a situation at work. I kept getting frustrated because she wasn't tracking the significance of certain events. I later realized I was describing events as significant without explaining the organizational context that made them significant. The politics involved are completely obvious to me from living inside them. She was hearing a sequence of events with none of the subtext.

[Management] We onboarded a new analyst with a written guide I'd assembled over several years. She came to me on day three with a list of questions that the guide didn't answer. Looking at her list, every question was about context and purpose — why we track certain things, what decisions the reports feed, who uses what and why. The guide explained how to do everything. It explained nothing about why. The why was so embedded in my work that I'd never thought to write it down.

[Family] I was trying to teach my twelve-year-old to cook a simple pasta dish. I told him to "season it properly." He added a large amount of salt and it was inedible. When I cook, I know what "properly seasoned" tastes like from thirty years of cooking. He has no reference for it. I'd given an instruction that required knowledge he didn't have. I should have said a specific amount. I should have had him taste it and compare. Instead I said "properly" and assumed he'd know.

[Technical] The internal tool I built has no documentation because to me it's self-explanatory. I know where every button leads because I built the logic. New people on the team frequently ask me how to accomplish basic tasks. I keep saying "it's pretty intuitive." For me it is — I understand the data model, the workflow, and the design decisions. They don't have any of that. The interface makes complete sense given what I know and none at all without it.

[Educational] I was reviewing my co-author's contribution to our shared paper. I told her the argument in section three "didn't land." She asked what I meant. I struggled to explain. The gap I was seeing was so obvious to me — a missing inferential step — that I couldn't reconstruct where the section needed to be different until I sat down and walked through it out loud. The gap had been invisible to her because she'd never seen what the complete argument looked like in my head.

[Medical] I counseled a family about their father's prognosis. I thought I'd been clear that the situation was serious. They came to the follow-up appointment asking questions that made it clear they hadn't understood the severity. I hadn't used the word "terminal." I'd used clinical language about "limited treatment options" and "disease trajectory." That language maps onto a specific clinical meaning for me. For them, it left enormous room for hope that wasn't realistic.

[Management] I wrote a strategy memo and sent it to the leadership team asking for feedback by Friday. Nobody responded with substantive feedback. When I followed up, two people said they hadn't been sure what kind of feedback I was looking for. I thought "feedback" was clear. In my mind I wanted specific critiques of the strategic logic. To them, feedback on a memo written by the CEO could mean many things, and none of them were sure which I wanted.

[Financial] I described my investment thesis to a potential co-investor. I thought I explained it clearly. He asked questions that showed he hadn't understood the basic premise. I'd described the thesis in terms of market structure dynamics that seem fundamental to me because I've been investing in this sector for eight years. To someone coming in fresh, I'd skipped the foundation entirely and started from mid-air.

[Technical] I was mentoring a junior designer and told her the wireframe needed more "hierarchy." I gave it back with a comment. She revised it and I still didn't see hierarchy. She was genuinely trying. The concept of visual hierarchy is so deeply ingrained in how I see design that I couldn't describe it in terms that gave her something actionable. I kept using the word. She kept trying to figure out what I meant. We kept talking past each other.

[Legal] I explained to a new client that we would "handle discovery." He later told a colleague that he was expecting us to handle all the documents without any involvement from him. He showed up to a large document review session unprepared. In my practice, "we handle discovery" means we lead the process and require extensive client participation. To him, "handle" meant we'd take care of it. The phrase is so routine in my professional vocabulary that I never unpacked what it actually implied.

[Social] I tried to give my younger colleague advice about navigating a difficult manager. I said things like "you need to manage up" and "read the room before the one-on-ones." She nodded. She came back the next week and had done the opposite of what I'd meant. "Managing up" is a concept that's vivid to me from years of corporate experience. To someone three years into their career, the phrase sounds clear and means something entirely different.

[Educational] I gave my undergraduate thesis student a model paper to read as an example of what I was looking for in her literature review. She came back with a review that had absorbed the model's surface features — the length, the subheadings — but missed the analytical moves I was hoping she'd absorb. The analytical moves are completely visible to me when I read that paper. I'd never explained what they were or that they were what I wanted her to notice.

[Family] I showed my elderly mother how to video call me on her tablet. I showed her twice. She hasn't been able to do it independently since. I keep saying it's simple — just open the app and press the green button. Simple to me means something that I can do with no conscious effort. Simple to her is a four-step sequence on a device that doesn't match any mental model she has from prior experience. I've described the steps but I've never thought about it from where she's starting.
