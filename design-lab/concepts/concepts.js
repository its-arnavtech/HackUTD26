const view = new URLSearchParams(location.search).get('view');
if (view === 'a' || view === 'b') document.body.dataset.view = view;
const backdrop = document.querySelector('.dialog-backdrop');
const close = document.querySelector('.dialog-close');
let trigger;
function showDialog(button, title, copy) {
  trigger = button;
  document.querySelector('#dialog-title').textContent = title;
  document.querySelector('.dialog-copy').innerHTML = copy;
  backdrop.hidden = false;
  close.focus();
}
function closeDialog() { backdrop.hidden = true; trigger?.focus(); }
document.querySelectorAll('[data-block]').forEach(button => button.addEventListener('click', () => showDialog(button, 'You decide what happens.', '<p>In the prototype, this tap will simulate blocking the sender.</p><p>This concept review doesn’t change any messages.</p>')));
document.querySelectorAll('[data-trail]').forEach(button => button.addEventListener('click', () => showDialog(button, 'Three checks. One clear reason.', '<p><b>1 · Link</b><br>Doesn’t belong to Capital One.</p><p><b>2 · Sender</b><br>Doesn’t match an official channel.</p><p><b>3 · Recent activity</b><br>No unusual transfers found in the last 7 days.</p><p>Authored, synthetic evidence for this design review.</p>')));
document.querySelectorAll('[data-recovery]').forEach(button => button.addEventListener('click', () => showDialog(button, 'We’ll take it step by step.', '<p>The chosen prototype will guide Linda through checking recent activity and a recovery checklist.</p><p>Nothing happens to her account automatically.</p>')));
close.addEventListener('click', closeDialog);
backdrop.addEventListener('click', event => { if (event.target === backdrop) closeDialog(); });
document.addEventListener('keydown', event => {
  if (backdrop.hidden) return;
  if (event.key === 'Escape') closeDialog();
  if (event.key === 'Tab') { event.preventDefault(); close.focus(); }
});
