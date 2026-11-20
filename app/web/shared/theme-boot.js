// Runs before the first paint (a classic script in <head>; the CSP allows no inline script) so a
// saved dark choice never flashes light first. Light is the default whatever the OS says: only a
// stored "dark" changes it.
(function () {
  try {
    if (localStorage.getItem('dn-theme') === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
  } catch (e) { /* storage unavailable: stay light */ }
})();
