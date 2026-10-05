/** Shown while a page loads. */
export default function Loading() {
  return (
    <p role="status" className="text-text-secondary">
      Loading. If the server was asleep, this can take up to 30 seconds.
    </p>
  );
}
