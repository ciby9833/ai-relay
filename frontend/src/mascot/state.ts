import type { ThreadMessage } from '../api';
import { resolveEmotion, type EmotionId } from './engine.js';

/** Expressions decorate real state; an AI hint cannot claim an approval or completion. */
export function messageEmotion(message?: ThreadMessage): EmotionId {
  if (!message || message.role !== 'assistant') return 'idle';
  const cards = message.cards ?? [];
  const actions = cards.flatMap(card => 'action' in card && card.action ? [card.action]
    : card.kind === 'item' && card.item?.action ? [card.item.action] : []);
  if (message.error || (message.toolFailed && !message.activeTool) || actions.some(action => action.status === 'failed') || cards.some(card =>
    (card.kind === 'file' && card.status === 'failed') || (card.kind === 'mission' && card.mission?.status === 'failed'))) return 'error';
  if (message.pending) {
    if (message.activeTool) return /^(search|read|list|get|find|fetch|query|browse|inspect)/.test(message.activeTool) ? 'searching' : 'working';
    if (message.text) return 'speaking';
    const hint = resolveEmotion(message.emotionId);
    return ['happy', 'surprised', 'thinking', 'questioning', 'sad', 'focused', 'proud'].includes(hint) ? hint : 'thinking';
  }
  if (actions.some(action => action.status === 'pending') || cards.some(card => card.kind === 'draft' && !card.action)) return 'waiting_approval';
  if (cards.some(card => card.kind === 'mission' && card.mission &&
    (card.mission.status === 'asking' || card.mission.pending_actions?.some(action => action.status === 'pending')))) return 'waiting_approval';
  if (cards.some(card => card.kind === 'file' && ['queued', 'running'].includes(card.status ?? ''))) return 'working';
  if (cards.some(card => card.kind === 'mission' && card.mission?.status === 'waiting')) return 'waiting';
  if (cards.some(card => card.kind === 'mission' && card.mission?.status === 'active')) return 'working';
  if (message.toolFailed) return 'error';
  if (actions.some(action => action.status === 'done') || cards.some(card =>
    (card.kind === 'file' && card.status === 'done' && card.verified?.ok === true) ||
    (card.kind === 'mission' && card.mission?.status === 'done'))) return 'completed';
  const hint = resolveEmotion(message.emotionId);
  return ['happy', 'surprised', 'thinking', 'questioning', 'sad', 'focused', 'proud'].includes(hint) ? hint : 'idle';
}
