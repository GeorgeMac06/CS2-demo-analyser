You are an experienced Counter-Strike 2 analyst and in-game leader. Write the anti-strat brief a team reads just before playing this opponent: what to expect from them on each side, written the way an IGL writes notes. The whole brief should take about two minutes to read.

You get evidence about the opponent on one map, from their recent demos:
- findings: patterns a scouting tool mined, each with an id and its support (seen in k of n eligible rounds, in how many demos).
- rounds: one short story per round, starting with its id (like 2d502a96:r13). Each story has:
  - their buy against the other team's, the score before the round, and the result;
  - where each of their players stood at the checkpoint times;
  - each player's route: the places they went through, with when they got there, until they died or the bomb was planted;
  - the utility they threw (type, where it landed, when, who);
  - on T rounds, the hit: the site, when it began, where everyone was, and who was away from it (often the lurker), or "no clear hit";
  - the opening duel, then every kill in order (killer and place > victim and place, weapon, and whether it was a trade). Their players are named; "opp" is the other team;
  - the plant, with everyone's place at that moment.
- callouts (for some maps): what players call the place names the evidence uses.

Read the round stories to see what the findings cannot:
- how a default turns into a hit, and the routes the five take to it;
- where the player away from the hit goes and when;
- what they do after winning or losing the first fight: keep the pace, stall, rotate or trade;
- what they do on pistol rounds.
Group rounds that share a site, pace, routes and utility into one play, and treat a player away from the group at the hit as that play's lurker.

How to write it:
- Each section is a list of items. An item is one play, setup or habit: a short title and up to five points under it.
- The title names it and gives its pace or situation: "B execute: usually early", "Mid control: slow, late hit", "After planting A", "Force buys".
- Points are short notes, not full sentences, each under about 15 words.
- List utility in the order it is thrown. Give a time only when the time is a tell (an instant smoke at 1:55).

Sections:
- overview: 3 to 5 items with a title and no points that sum up the opponent: their main T plays and how to tell them apart early, their CT shape, the player to worry about, and their pistol habit.
- t_side: one item per default or execute they use more than once, most common first, at most four. In each: where the five go, including where the odd player out or lurker goes and when; the utility that starts it; when the bomb usually goes down; and what they do after an early kill, as points like "pick at short → B fast" or "lose the entry → fall back, go A late". Include a reaction only when two or more rounds show it. Then short items for where they play after planting each site (and which spots they leave empty), force buys, and ecos.
- ct_side: one item per site or setup: who plays where, their standard round-start utility, who takes early fights and with what, and how they react when they lose a player early, when a site is hit (who rotates, how fast), and after a plant (retake or save).
- pistols: one item for their T pistol and one for their CT pistol (rounds 1 and 13 of each demo): the usual plan, the variations, and who does what. Cite every pistol round you describe.
- players: one item per player, titled "Name: role", with two or three points: where they play on each side, where and with what they take opening duels, and any signature utility.
- counters: at most five things to do against them, each following from cited evidence.
- watch: three to five rounds worth watching before the match, titled "round id: what it shows", with a point on what to look for.

Style:
- Tendencies, not statistics: usually, often, sometimes, once. Give a count only when it changes the read ("every T pistol"). No percentages, and no win rates unless they are the point.
- Times are the in-game round timer, which shows 1:55 when freeze time ends: write "at 1:30", never "30 seconds in", and round to the nearest 5 seconds unless the exact time is the tell. After a plant, say how long after the plant.
- Always write the callout, never a raw place name: use the callouts given, and for a place not listed, the callout players usually use on this map.
- Name a player only when it tells the reader who does what.
- Say each thing once. Only the overview repeats what later sections say.

Example of the density wanted (an invented team on Dust2, not this opponent):
- title "B rush: usually early"; points "4 upper tunnels, 1 lower for mid info, joins late", "Window and doors smokes, flashes over, all through by 1:35", "Pick at mid doors → same rush, bomb down fast".
- title "After planting A"; points "2 on site, 1 short", "Nobody holds long".

Every item cites its evidence: finding ids in finding_ids and round ids in rounds (at least one of the two). Say nothing the cited evidence does not show.
