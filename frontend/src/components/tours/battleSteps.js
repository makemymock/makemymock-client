export const battleTourSteps = [
  {
    target: '[data-tour="battle.tabs"]',
    title: 'Two views',
    body: 'Find an opponent here, or jump to Battle history to see how your past matches went.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="battle.play"]',
    title: 'Head‑to‑head',
    body: 'Press Play to enter the queue. The next student who joins within 15 seconds is your opponent.',
    placement: 'right',
  },
  {
    target: '[data-tour="battle.perks"]',
    title: 'The rules',
    body: 'Five questions, fifteen seconds each, same questions for both of you. Faster correct answers score more.',
    placement: 'top',
  },
  {
    title: 'Battle history',
    body: 'Every match is saved — switch to the Battle history tab any time to see your wins, losses, and how you’re trending.',
    placement: 'center',
  },
];
