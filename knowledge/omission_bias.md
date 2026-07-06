# Omission Bias

## Definition
The tendency to judge harmful actions as worse than equally harmful inactions, and to prefer inaction over action even when the expected outcomes are identical. People hold themselves and others to a higher moral and causal standard for harms that result from doing something than for equivalent harms that result from failing to act. The bias has evolutionary and cultural roots — action is more visible and attributable than inaction — but it produces suboptimal decisions in medical ethics, policy, finance, and risk management, where inaction frequently causes harm equal to or greater than equivalent action.

## Examples
In medicine, omission bias is central to vaccination hesitancy: parents who fear that a vaccine might cause a rare adverse event — a harm from action — resist vaccination even when they acknowledge that not vaccinating creates higher risk of disease — a harm from inaction. The action is judged as more culpable than the equivalent inaction.

In finance, fund managers who lose money by doing nothing ("holding through a crash") are judged less harshly than fund managers who lost the same amount by making an active trade, even when the expected value of both strategies was equivalent at the time of decision.

In law, "do no harm" principles in medical ethics and the higher standard for acts versus omissions in legal negligence doctrine institutionalize omission bias in formal systems.

In policy, governments often find it politically easier to allow a harm to continue through inaction than to implement a policy that prevents a larger harm but creates a smaller visible risk — because the action is attributable and the inaction is diffuse.

In software development, developers are more likely to ship unchanged code with known bugs than to refactor — the action of changing code feels riskier even when the cost of the bugs exceeds the cost of the refactor.

## Indicators
- Feels that causing harm by doing something is worse than causing the same harm by doing nothing
- Defaults to inaction when evidence supports acting, because taking action feels riskier than staying still
- Blames someone who acted and caused harm more harshly than someone who did nothing and caused the same harm
- Treats "not acting" as a safe neutral position even when inaction has predictable negative consequences
- Resists a preventive intervention because the harm it would prevent is statistical and abstract rather than immediate and concrete

## False Positives
- In genuinely reversible decisions, preference for inaction pending more information is appropriate caution rather than omission bias
- Legal and ethical frameworks that distinguish acts from omissions may reflect genuine moral distinctions in cases where agency and causation differ meaningfully
- When the consequences of action are more uncertain than the consequences of inaction, preferring inaction is rational risk management, not bias

## Related Biases
Status Quo Bias, Zero-risk Bias, Loss Aversion, Negativity Bias

## Story Patterns

[Medical] My daughter's pediatrician recommended the standard vaccine schedule. I've been reading about a small number of reported adverse reactions. I decided to delay some of the vaccines. I know that not vaccinating means a real risk of disease. I know the adverse event rate is much lower than the disease risk. But if something goes wrong after I actively give my daughter a shot, I feel like that's on me in a way that a disease she catches naturally wouldn't be. The action feels like more responsibility.

[Management] Our HR policy requires annual performance documentation. I have an employee who is clearly underperforming — the evidence is there, the team is frustrated, multiple conversations have happened. I haven't done the formal documentation yet. Filing the formal paperwork feels like the step that makes the problem real and puts me in a position where something has to happen. As long as I haven't filed it, the situation still feels manageable in an informal way. I know I'm letting it drift.

[Financial] My investment portfolio has an allocation that made sense five years ago. I should rebalance. I know the arguments — my risk profile has shifted, the original allocation is no longer optimal, the data is clear. But if I actively rebalance and the new allocation underperforms, that outcome is on my decision. If I do nothing and the old allocation underperforms, that feels like the market's fault. Keeping it the same doesn't feel like a choice. It doesn't feel like anything.

[Legal] I know our vendor is not fully complying with the terms of our service agreement. I've documented it internally. The cost of the non-compliance is real but not catastrophic yet. I haven't sent the formal notice of non-compliance that the contract requires. Sending notice starts a process — remediation demand, escalation, potential litigation. I can see how that plays out. If I do nothing, the non-compliance continues but I haven't made any of those things happen. Not sending the notice doesn't feel like a decision.

[Technical] We have a known vulnerability in a legacy component of our system. It's in a rarely-accessed part of the codebase and the attack surface is limited. I've been sitting on the decision to either patch it or isolate it for six weeks. If I patch and introduce a regression, I caused that regression. If I don't patch and someone exploits the vulnerability, I feel like the vulnerability existed before my tenure on the team. Not acting feels less mine than acting.

[Political] The city council voted on whether to update road safety infrastructure at a known hazard intersection. Several council members said the current configuration "hasn't caused a fatality yet." They voted against the update. Three months later someone was seriously injured at that intersection. At no point did anyone weigh the ongoing risk of the unchanged intersection against the risk of the new configuration. The old configuration had a track record; the new one had uncertainty. Inaction felt like the safe choice even though it carried ongoing risk.

[Social] My friend group has a member whose behavior has been making others uncomfortable for two years. We've all talked about it among ourselves. Nobody has said anything directly to him. Having the conversation feels risky — he might react badly, it might change the group dynamic, something might go wrong from the action of confronting it. Not having the conversation keeps everything the same even though everything is actually already not fine. We keep choosing not to say anything and calling it being careful.

[Family] My elderly father's driving has been getting worse. My siblings and I have talked about this privately for months. Nobody has brought it up with him. If we say something and he gets upset and stops speaking to us, we'll have caused that. If he has an accident because we didn't say anything, that feels like it would have happened anyway — the accident, not us. I know logically that not saying something is also a choice with consequences. It doesn't feel that way from the inside.

[Educational] I have a student who I'm fairly confident is struggling with something beyond academics — he shows signs of significant distress. I've been thinking about whether to refer him to campus counseling. If I refer him and he feels intruded upon, I've made something worse. If I don't refer him and his situation deteriorates, that feels like something that happened to him, not something I failed to prevent. Not acting feels like preserving the status quo rather than risking a harm.

[Consumer] My home has some deferred maintenance — a few things that should be addressed. I've gotten quotes. The one that concerns me most is a roof repair that would cost $8,000. The roof might be fine for another few years. If I get the repair done and the roofer introduces a new problem or my HOA has an issue with how it was done, I'll have caused that. If I wait and the roof leaks, that's what old roofs do. The action feels more mine than the inaction.

[Management] Our team has a testing protocol gap that could allow a certain class of bugs through to production. Fixing it requires a sprint's worth of work. We haven't fixed it. If we add the testing and a bug we introduced makes it through anyway, the failure is visible and recent. If we continue with the gap and a bug slips through because of it, that feels like a preexisting condition. Adding the test and having a failure would feel worse than not adding it and having a failure. I know that's not rational. It's how the team discussion keeps going.

[Financial] I'm aware that my parents don't have an updated estate plan. Theirs is from 2003 and doesn't reflect their current situation or wishes. I've been meaning to raise it for two years. If I raise it and the conversation goes badly — they get upset, it creates family stress — I will have started that. If I don't raise it and something happens before they update their documents, I didn't cause that. Not bringing it up keeps me out of the causal chain in a way that bringing it up would end.

[Legal] A supplier sent us a contract addendum with terms that are worse than our existing agreement. Our current agreement is set to expire in four months. If I sign the addendum, I've actively accepted worse terms. If I don't sign it and the existing agreement lapses without renewal, we might end up in a weaker position — but that would have happened through time passing, not through a decision I made. I've been waiting for the deadline without deciding. Waiting feels like not-deciding. It's actually deciding by default.

[Technical] Our alerting thresholds haven't been recalibrated since 2021. False positive rates are high and the team has developed alert fatigue — real signals are being missed because of the noise. Recalibrating requires someone to make a series of judgment calls that might increase genuine missed alerts for a period. Every engineer I've asked agrees the current state is bad. Nobody has volunteered to own the recalibration. Leaving it as-is feels like not causing anything new, even though alert fatigue is actively causing harm.

[Medical] I have elevated blood pressure. My doctor has given me clear guidance about lifestyle changes that would reduce it and discussed medication as an option. I haven't made all the lifestyle changes and I've resisted starting medication. If I take medication and have a side effect, I'll have caused that by taking the medication. If I don't take medication and have a cardiovascular event, that feels like something my biology did, not something my decision did. My doctor has pointed out that this is not how medical causation works. The feeling persists.

[Social] My neighbor has been playing music too loudly at night for several months. I've been avoiding saying anything. If I knock on his door and it goes badly — confrontation, resentment, a worse dynamic in the building — I will have made that happen. If I keep not saying anything, the noise continues but I didn't make it worse. Every time I consider knocking, the calculus is the same: the thing I could make worse by acting versus the thing that's just happening while I don't act.

[Family] My teenager has been spending an unhealthy amount of time online. I've been meaning to set clearer boundaries for months. Setting limits will cause conflict. He'll be angry. There will be arguments. Those are harms I'll have directly caused by acting. The current pattern continues without those specific arguments happening. The harm from the current pattern is diffuse and slow-moving. The harm from the intervention is immediate and attributable to me. I keep delaying.

[Educational] I've been assigned a student for independent study whose prior work suggests they're underprepared for the project they've proposed. I could recommend they revise the project scope, which might disappoint them or damage our working relationship. Or I could accept the project as proposed, let them try, and see what happens. If I intervene and it upsets them, that's from my action. If I don't intervene and they struggle or fail, that's what happened because the project was hard. I approved the proposal.

[Financial] The hedge fund I'm invested in has changed its strategy somewhat from what I initially bought. The adjusted strategy has more concentration risk. I should probably exit. But exiting means actively selling, actively reallocating, actively being the one who made that move. If I stay and the concentrated position goes badly, I can say I didn't make any new decisions — the original investment just had a bad outcome. If I exit and something goes wrong in the reallocation, I caused that.

[Management] An employee on my team has a skill gap that is limiting the whole team's output. Addressing it directly — putting her on a development plan — feels like creating a difficult and potentially harmful situation. Not addressing it allows the team to continue underperforming, but that underperformance doesn't feel like something I created. The damage from my inaction is real and ongoing. The risk from my action is vivid and attributable. I've been letting the performance issue drift.

[Technical] Our database schema has technical debt that should be addressed. The migration required is disruptive. If I initiate the migration and something goes wrong, I'm the one who initiated it. The existing schema has known costs but they're ongoing background costs that feel inherited rather than created. Every sprint planning session, I push the migration to the next one. The debt is getting worse. The decision to address it keeps feeling like too much to own.

[Political] A regulatory agency had data suggesting a product might pose a moderate risk to a small population segment. Acting on it — requiring labeling changes or use restrictions — was an active regulatory decision with visible industry opposition. Not acting meant the existing product continued on the market. The potential harm from inaction was statistical and distributed. The harm from action was immediate and politically attributable. The agency didn't act. The product stayed on the market. The harms from inaction were real but they didn't have a decision attached to them.

[Legal] I know a former client's business partner is engaged in fraudulent activity that is likely to harm other investors. I've been trying to determine whether I have an obligation to report it. Reporting would mean actively taking a step that creates friction, possible blowback, and legal uncertainty about my role. Not reporting means the fraud continues but my silence isn't the fraud — the fraud is the other person's action. The act of reporting feels more mine than the consequence of not reporting.

[Family] My parents' house has safety hazards that worry me — a loose handrail on the stairs, an outdoor step that's uneven. Getting those fixed requires hiring someone, managing the visit, possibly having a conversation with my parents about safety that they'll find patronizing. If I arrange the repairs and the contractor damages something, I caused that. If I don't arrange the repairs and my father falls on that step, that was the step's fault. Every month I don't call a contractor, the step is still there.

[Consumer] I've known for a year that my car has a recall. The fix is free and takes an hour. I haven't scheduled it. Scheduling it means taking a day out, arranging a ride, and actively putting the car into a process where something could go wrong. If I don't schedule it and the recalled part fails, that's the defect's fault. If I schedule the repair and something goes wrong during it, that's something I set in motion. I've been living with the recall for twelve months.

[Educational] Our course syllabus has a grading policy that creates perverse incentives — students get credit for submitting anything, which has led to low-effort submissions inflating grade distributions. I've been meaning to revise it for two semesters. If I revise it and grades drop and students complain, I changed the policy and made that happen. If I don't revise it, the incentive problem continues but no one can point to a change I made. Next semester I'll address it, I keep telling myself.

[Technical] We have a third-party integration that has a known security concern. The vendor has released a patch. Applying the patch requires a maintenance window and carries small but real risk of regression. Not applying it means the known security concern persists, but it's a preexisting condition. The regression from applying the patch would be something we introduced. The ongoing security exposure from not patching would be something we inherited. We've been running without the patch for three months.

[Social] I've been watching someone in my professional network behave unethically toward colleagues. I know several of the affected people. Saying something — to him directly, to mutual colleagues, or to a relevant professional body — would mean actively inserting myself into something. Things could go wrong from my action. If I stay quiet and the behavior continues, I didn't cause any of what continues. The discomfort of acting feels more owned than the discomfort of watching.

[Management] Our customer success team has a documented process that isn't being followed consistently. I've known about the gap for a quarter. Formally mandating the process and building accountability around it means creating a situation with enforcement, possible resentment, and the risk of getting the implementation wrong. Letting the inconsistency continue means things stay roughly as they are. The harm from inconsistency is real. The risk from the mandate is more visible. I've been letting it continue.

[Political] A city had clear data that a specific intersection was dangerous. Redesigning it to add a traffic signal would have cost $200,000. The city did not act. A child was killed at the intersection the following year. At the council inquiry that followed, members described themselves as having not made the decision to leave the intersection as-is — they simply hadn't made the decision to change it. The distinction they were drawing was between acting and not acting. The outcome was the same.
