# Planning Fallacy

## Definition
The tendency to underestimate the time, costs, and risks of future actions and overestimate the benefits of those plans, even when aware that similar past projects have overrun. The planning fallacy arises from optimism bias and the inside view — planners focus on the specific details of the current project rather than the distributional outcomes of similar past projects (the outside view or reference class forecasting). It affects individuals, teams, organizations, and governments consistently across domains, producing chronic schedule overruns and budget shortfalls.

## Examples
In software development, teams routinely underestimate project completion time by factors of two to three. This is so consistent it has its own name — Hofstadter's Law — "It always takes longer than you expect, even when you take into account Hofstadter's Law."

In infrastructure, an analysis of 258 major infrastructure projects found that 86% overran their budget, with an average overrun of 28%. The Channel Tunnel cost 80% more than planned; the Sydney Opera House cost 1,400% more than the original estimate.

In personal finance, people consistently underestimate how long it will take to pay off debt, how much a home renovation will cost, and how many months it will take to find a job after a layoff.

In academia, dissertations and research projects routinely take twice as long to complete as students and researchers initially estimate, regardless of the field or the researcher's experience level.

In product launches, marketing teams consistently overestimate adoption rates and underestimate the time required to acquire early customers in new markets.

## Indicators
- Sets a deadline or budget based on how long the work would take if everything goes right, not how long it typically takes
- Does not consult how long similar projects have actually taken before committing to a timeline
- Treats the best-case scenario as the expected case when building a plan
- Plans with insufficient contingency because identified risks feel unlikely rather than because they have been measured
- Revises timelines and budgets upward as the project progresses rather than starting from realistic historical estimates

## False Positives
- Deliberately setting aggressive targets to motivate a team is a management tactic, not planning fallacy — the bias involves sincere underestimation, not strategic goal-setting
- Genuinely novel projects with no reference class may require optimistic early estimates that are refined as information becomes available — this is appropriate uncertainty, not bias
- Accurate early-stage estimates in domains where planners have strong historical calibration are not planning fallacy

## Related Biases
Optimism Bias, Overconfidence Bias, Sunk Cost Fallacy, Availability Heuristic

## Story Patterns

[Technical] I told my team we'd ship the feature in two weeks. Three weeks in I was still working out the edge cases. Five weeks in I shipped it. I had planned two weeks because I was thinking about the core implementation, not the testing, the documentation, the PR feedback cycles, or the deployment coordination. Two weeks was how long the code would take if everything went right and I did nothing else.

[Management] I committed to a client that the report would be ready in four weeks. My company had done similar reports in four to six weeks. I chose four. We finished at six. I'd told the client four because it sounded faster and more competent. The actual comparable history was four to six. Four was not a floor; it was the optimistic end of the range.

[Family] I said the kitchen remodel would take six weeks. It took four and a half months. The contractor warned me. I said he was being conservative to manage expectations. I thought I understood renovations because I'd watched others happen. Actually managing one, with its delays, supplier problems, and unexpected discoveries behind the walls, is different from observing one.

[Educational] My dissertation has been "almost done" for eight months. I said I'd have it finished in a summer. I'm now two summers in with a chapter that keeps expanding. Every time I think I understand the scope, I realize the current chapter requires something I haven't yet established. I should have asked my advisor how long dissertations in my field actually take. I didn't ask because I was sure I'd be faster.

[Financial] I budgeted $30,000 for the move and setup of the new office. We spent $54,000. I'd known the $30,000 was a rough estimate. I'd told the board $30,000 without a range and without a contingency line because $30,000 was what I hoped it would cost. Explaining why there's a $24,000 overrun on a $30,000 budget has been an uncomfortable conversation.

[Consumer] I started a home renovation planning to do it myself to save money. I thought three months, maybe four. It took eleven months and I ended up hiring contractors for about sixty percent of the work anyway. I hadn't accounted for how long it would take to learn what I didn't know, how many trips to the hardware store each task would require, or how long each step would take someone who had never done it before.

[Legal] I told my client we'd be through with discovery in six weeks. Discovery took five months. Large commercial litigation almost always takes longer than the initial estimate because document review expands, third-party subpoenas create delays, and opposing counsel does things you can't predict. I'd said six weeks because six weeks was what discovery would take if everything moved at the pace I envisioned when I was making the estimate.

[Management] We planned the software migration for one quarter. We're in our third quarter of migration work. I had planned one quarter because one quarter was how long the core technical work would take if we could dedicate everyone full-time and encounter no complications. We couldn't dedicate everyone full-time and we encountered complications.

[Social] I volunteered to organize the neighborhood association's annual event. I thought it would be a few hours of coordination a month leading up to it and then a day of event logistics. I'm six weeks in and I've already put in more hours than I'd estimated for the entire run-up. Every small decision branches into three smaller decisions and every email generates two replies. Organizing things is harder than planning them.

[Educational] I planned my research field study for three months. I'm now at seven months and my data collection isn't finished. The local context created complications I hadn't anticipated. Permits took longer than expected. Key informants were less available than the literature suggested. Some instruments didn't work the way I'd designed them. Every single one of those problems is a normal part of field research. I'd planned as if none of them would happen.

[Technical] I estimated the database migration at one sprint. It's been three sprints. Every sprint I say "this is the last sprint." The migration keeps revealing more complexity than was visible from outside. Each sprint I learn enough to see how much further there is to go. I should have accounted for the fact that with complex migrations, you can't fully see the scope until you're inside it.

[Management] I told my leadership team we'd complete the organizational redesign in three months. We're at eight months and still finalizing reporting structures. Organizational redesigns are never just structural — they're political, interpersonal, and cultural, and they take much longer when people's roles and status are changing. I'd planned for the structural part. The rest was not in my estimate.

[Financial] I estimated it would take six months to raise our Series A. It took eighteen months. I'd been told that fundraising takes longer than founders expect. I understood this as advice for less-prepared founders. I was prepared. My narrative was tight, my metrics were solid. The market turned mid-process, an anchor investor we'd counted on backed out, and we had to run a longer process. Eighteen months is not unusual. Six months was my optimistic scenario presented as a plan.

[Consumer] I said I'd read this 900-page book over my three-week vacation. I read 200 pages. I'd planned based on my ideal daily reading pace on mornings with nothing scheduled. Vacations have activities, people, fatigue, and distractions that don't appear in a pace calculation. My plan was for a reading pace, not a vacation.

[Political] We planned the ballot initiative for eight months from first draft to vote. It took sixteen months. Signature collection took longer than expected, the attorney general's office review extended our timeline, and a legal challenge delayed the submission by two months. None of those were exotic scenarios — all of them happen regularly in ballot initiative campaigns. My eight-month plan assumed a frictionless process.

[Technical] I told the client we'd migrate their data to the new platform in two weekends of work. We used five weekends and the sixth was cleanup. Their data was messier than their documentation suggested, the transformation logic had more edge cases than we'd scoped, and each weekend surfaced issues that needed addressing before the next step could proceed. The client had described their data; I'd estimated based on the description without the data.

[Educational] I planned to have all my course materials revised before the fall semester. I started in June. The semester began and I had revised about a third of the materials. Revising a course is not just rewriting slides — it involves reconsidering the scaffolding, updating examples, testing new activities, and reconciling new content with existing assessments. I'd planned for the time to type. I hadn't planned for the time to think.

[Management] We hired a team of contractors to build a custom integration. The SOW said three months. We signed the contract. Six months later we were still in development. The contractors were professional and experienced. The integration was more complex than the initial scoping sessions had revealed. This is standard for custom integrations. The three-month estimate had been produced at the scoping stage when neither party fully understood the problem.

[Financial] I said I'd complete the due diligence on the acquisition target in thirty days. It took ninety. Due diligence uncovers things that require investigation, which uncovers more things. The thirty-day plan was for a clean target. Targets are never entirely clean. The thirty-day plan had been my best-case estimate, presented as a plan.

[Social] I started a side project in February thinking I'd have it complete by summer. It's November. Every weekend I planned to work on it, something else came up. The project itself also kept revealing more scope as I got into it. Ambitious side projects expand in scope and contract in available time simultaneously. I had planned for neither.

[Technical] Our cloud cost optimization initiative was planned for two months. Four months in, we're still in the analysis phase. Optimizing cloud costs requires understanding your infrastructure at a level of detail that most teams don't have until they're in the optimization process. The two-month plan was for the implementation. The analysis phase it required first wasn't in the plan.

[Legal] I told my partner we'd settle the case before the year was out. It's the following spring. Settlement negotiations take as long as the other side wants them to take. I'd planned as if both parties would move at the pace I wanted to move. The other party had different incentives and a different timeline. My plan was for my side of the negotiation.

[Family] I planned to have my parents' house cleared and prepared for sale in one month after they moved to assisted living. Six months later I'm still finding things that need decisions, repairs that needed coordinating, and paperwork that needed filing. Estates and home preparation involve an enormous number of small tasks that each take longer than anticipated and generate follow-on tasks. One month was an estimate formed before I understood what the work actually involved.

[Educational] I estimated my online course project would take fifty hours to build from scratch. It took two hundred and forty hours. I'd underestimated the time for scripting each lesson, recording and re-recording sections, editing video, building assessments, creating learner materials, and testing the platform. My fifty-hour estimate had been for "recording and putting it together." That phrase had hidden everything that made up the actual work.

[Management] We planned the product roadmap for the year in January. By April we were significantly behind. The roadmap had been built assuming we'd be working on the roadmap items and nothing else would materialize. Every quarter brings emergent work — customer escalations, compliance requirements, internal platform needs, key hire departures. Roadmaps built without buffer assume the year will be only the things we can currently see.

[Technical] I planned a data science project to take eight weeks. It took twenty-five weeks. The data cleaning phase alone took more than half my original estimate. I'd planned for the modeling and analysis. Data cleaning, iteration with stakeholders on what outcomes actually matter, and rebuilding the pipeline when the initial approach didn't work were not in my original estimate. They're almost always in the actual project.

[Consumer] I estimated I could learn guitar to a beginner-performance level in a year of regular practice. I've been playing for three years and I'm at an intermediate level. Learning an instrument moves at its own pace regardless of how often you practice. I'd made my estimate based on what felt like a reasonable pace. The actual learning curve had different terrain than my projection.

[Political] We launched the campaign sixteen months before the election with a plan to build out our ground operation over the first year. The ground operation plan was about four months behind every milestone. Recruiting, training, and managing volunteers at scale is harder and slower than the plan acknowledged. We'd written the plan based on what the ground operation needed to look like, not on how long it actually takes to build one.

[Financial] I planned to have my taxes done in the first weekend of February. I filed an extension for the second consecutive year. Each February I underestimate the time required to gather all my documentation, reconcile investment accounts, and address the questions my accountant raises. I know from two years of experience that it takes longer. I plan for February anyway because February is when I intend to be done.

[Technical] My team estimated a refactoring project at three sprints. It's been eight sprints. Refactoring is the category of work that most reliably takes longer than anticipated because you can't fully see the entanglement of the existing code until you're inside it. Our initial estimate had assumed the code was structured the way we thought it was structured. It was structured the way it actually was, which was different.

[Management] I told the executive team the sales team restructuring would be complete and effective within two quarters. Effectiveness — people performing at the new structure's potential — took five quarters. The structural part was complete in two quarters. But people take time to build new relationships, new habits, and new skills. I'd planned for the org chart change. I hadn't planned for the time it takes for people to become the org chart.

[Educational] I planned to write and submit four academic papers this year. I submitted one. Papers take as long as the revision process takes, and the revision process is almost entirely outside the writer's control. Reviewer timelines, desk rejections, revision requests, and resubmission cycles don't fit into a calendar plan. I'd planned for writing four papers. I hadn't planned for publishing in the journal system as it actually operates.
