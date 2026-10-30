/** A2's local transport. E's screen/fixture files remain independently usable. */
import { mountConsumer } from './consumer.js';

export function createHttpAdapter() {
  async function read(response) {
    const result = await response.json();
    if (!response.ok && !result.state) throw new Error(result.error?.code ?? 'provider_unavailable');
    return result;
  }
  return {
    async state(requestId = null) {
      const query = requestId ? `?request_id=${encodeURIComponent(requestId)}` : '';
      return read(await fetch(`/api/state${query}`, { cache: 'no-store', credentials: 'same-origin' }));
    },
    async command(command) {
      return read(await fetch('/api/command', { method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) }));
    },
  };
}

const root = typeof document === 'undefined' ? null : document.querySelector('#consumer-app[data-adapter="http"]');
if (root) mountConsumer(root, createHttpAdapter());
