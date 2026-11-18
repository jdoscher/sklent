// First paint in the stored theme, before the stylesheets load (Kist's pattern).
// sk.theme is gallery (the default: renders are judged on neutral grey), dark,
// light or system. The hex values are each theme's --bg and --chrome from
// css/kist-tokens.css; js/theme.js reads the live tokens after load.
;(function () {
  var stored = 'gallery'
  try { stored = localStorage.getItem('sk.theme') || stored } catch (e) {}
  var theme = stored
  if (theme === 'system') {
    theme = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  }
  if (theme !== 'dark' && theme !== 'light') theme = 'gallery'
  var root = document.documentElement
  root.setAttribute('data-theme', theme)
  root.style.colorScheme = theme === 'light' ? 'light' : 'dark'
  root.style.backgroundColor = theme === 'gallery' ? '#5C5C5C' : theme === 'light' ? '#FAF9F6' : '#131312'
  var bar = theme === 'gallery' ? '#5C5C5C' : theme === 'light' ? '#FFFFFF' : '#1C1C1A'
  var meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', bar)
})()
