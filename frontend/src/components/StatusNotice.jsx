import Icon from "./Icon.jsx";

export default function StatusNotice({ message, onRetry, retryLabel = "Try again" }) {
  if (!message) return null;
  return (
    <div className="status-notice" role="alert">
      <Icon name="alert" size={18} />
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="plain-button" onClick={onRetry}>{retryLabel}</button>
      )}
    </div>
  );
}
