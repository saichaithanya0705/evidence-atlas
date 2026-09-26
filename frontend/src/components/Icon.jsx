const shapes = {
  search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 5 5" /></>,
  chevron: <path d="m6 9 6 6 6-6" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  file: <><path d="M6 3.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 20V5a1.5 1.5 0 0 1 2-1.5Z" /><path d="M14 3.5V8h4M7.5 12h7M7.5 15.5h7" /></>,
  pencil: <><path d="m4 16.8-.8 4 4-.8L19 8.2a2.4 2.4 0 0 0-3.4-3.4L4 16.8Z" /><path d="m13.8 6.6 3.4 3.4" /></>,
  filter: <path d="M3 4h18l-7 8v6l-4 2v-8L3 4Z" />,
  download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4" /><path d="M4 16v4h16v-4" /></>,
  external: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M17 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h6" /></>,
  quote: <><path d="M10 11H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5v8a5 5 0 0 1-5 5" /><path d="M21 11h-5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5v8a5 5 0 0 1-5 5" /></>,
  alert: <><path d="M12 3 2.8 19a1.4 1.4 0 0 0 1.2 2h16a1.4 1.4 0 0 0 1.2-2L12 3Z" /><path d="M12 9v5m0 3h.01" /></>,
  arrow: <><path d="M4 12h15m-6-6 6 6-6 6" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.7 9a2.4 2.4 0 1 1 4.2 1.6c-1.2 1-1.9 1.4-1.9 3m0 3h.01" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  book: <><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22V4.5Z" /><path d="M4 5v17m4-16h8m-8 4h8" /></>,
  pulse: <><path d="M3 12h4l3-7 4 14 3-7h4" /></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></>,
  check: <path d="m5 12 4 4L19 6" />,
};

export default function Icon({ name, size = 18, className = "" }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {shapes[name]}
    </svg>
  );
}
