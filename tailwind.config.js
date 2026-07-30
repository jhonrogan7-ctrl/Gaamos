/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
    './design/wireframes/**/*.html',
  ],
  // Unused single-class @layer components rules get tree-shaken; no template
  // references these yet (spec 2026-07-30). Remove in Task 4, once
  // _multibranch.html and home.html reference all three.
  safelist: ['mk-print-rule', 'mk-print-dark', 'mk-print-rosette'],
  theme: {
    extend: {
      colors: {
        accent: 'var(--accent)', 'accent-deep': 'var(--accent-deep)',
        'accent-soft': 'var(--accent-soft)', 'accent-ink': 'var(--accent-ink)',
        ink: 'var(--ink)', 'ink-2': 'var(--ink-2)', 'ink-3': 'var(--ink-3)',
        line: 'var(--line)', 'line-2': 'var(--line-2)',
        bg: 'var(--bg)', panel: 'var(--panel)',
        side: 'var(--side)', 'side-2': 'var(--side-2)', 'side-ink': 'var(--side-ink)',
        green: 'var(--green)', 'green-soft': 'var(--green-soft)',
        amber: 'var(--amber)', 'amber-soft': 'var(--amber-soft)',
      },
      fontFamily: {
        hd: ['Bricolage Grotesque', 'sans-serif'],
        bd: ['Plus Jakarta Sans', 'sans-serif'],
      },
      borderRadius: { xl2: '16px' },
      boxShadow: { frame: '0 30px 70px -28px rgba(20,23,31,.55)' },
    },
  },
  plugins: [],
};
