export default function FileAction({ icon, title, onClick }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        padding: '2px 6px',
        borderRadius: 4,
        border: '1px solid rgba(255,255,255,0.1)',
        background: 'rgba(255,255,255,0.05)',
        cursor: 'pointer',
        fontSize: 11,
        lineHeight: 1,
      }}
      onMouseEnter={(event) => { event.currentTarget.style.background = 'rgba(255,255,255,0.12)'; }}
      onMouseLeave={(event) => { event.currentTarget.style.background = 'rgba(255,255,255,0.05)'; }}
    >
      {icon}
    </button>
  );
}
