import { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Check,
  Copy,
  ImagePlus,
  Menu,
  RefreshCw,
  Settings,
  Soup,
  Wrench,
  X,
  Clock3,
} from 'lucide-react';
import {
  streamChat,
  streamInternalHandoff,
  streamOpening,
  getCurrentSession,
  newSession,
  getProfile,
  getSessionCalendar,
  getSessionBasket,
  getIngredientList,
  clearCalendarDay,
  selectCalendarWeek,
  generateDayDetails,
  buildGroceryList,
  setBasketCount,
  removeBasketItem,
  streamFillBasket,
  streamSourceItem,
  apiUrl,
} from '../api.js';
import ProfileModal from './ProfileModal.jsx';
import HistoryModal from './HistoryModal.jsx';
import ToolsModal from './ToolsModal.jsx';
import MarkdownMessage from './MarkdownMessage.jsx';
import YouTubeGallery from './YouTubeGallery.jsx';
import MealPlannerCalendar from './MealPlannerCalendar.jsx';
import MealDetailModal from './MealDetailModal.jsx';
import BasketBoard from './BasketBoard.jsx';
import PravaCheckoutModal from './PravaCheckoutModal.jsx';
import thinkingImage from '../assets/thinking.png';

const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

function freshAssistantMessage(overrides = {}) {
  return { role: 'assistant', text: '', tools: [], activeTool: null, liveStatus: null, ...overrides };
}

function liveStatusForTool(toolName) {
  switch (toolName) {
    case 'show_calendar':
      return {
        title: 'Opening meal planner...',
        detail: 'Boppai is updating the calendar.',
      };
    case 'show_basket':
      return {
        title: 'Updating basket...',
        detail: 'Boppai is updating your basket.',
      };
    case 'show_chat':
      return {
        title: 'Returning to chat...',
        detail: 'Boppai is closing the current surface.',
      };
    case 'start_prava_checkout':
      return {
        title: 'Starting Prava...',
        detail: 'Opening the secure payment panel.',
      };
    case 'get_profile':
      return { title: 'Checking your profile...', detail: 'Boppai is using your saved context for this reply.' };
    case 'save_profile':
      return { title: 'Saving your profile...', detail: 'This reply is still in progress.' };
    default:
      return { title: `Running ${toolName}...`, detail: 'This reply is still in progress.' };
  }
}

function liveStatusForLabel(label) {
  if (!label) return null;
  if (label === 'thinking') return { title: 'Thinking...', detail: 'Boppai is working on the reply.' };
  if (label === 'initializing') return { title: 'Starting...', detail: 'Connecting to the agent.' };
  return { title: `${label}...`, detail: 'This reply is still in progress.' };
}

function toolChipLabel(toolName) {
  if (toolName === 'show_chat') return 'chat';
  if (toolName === 'show_calendar') return 'calendar';
  if (toolName === 'show_basket') return 'basket';
  if (toolName === 'start_prava_checkout') return 'Prava';
  return toolName;
}

function calendarFromToolInput(input) {
  let value = input;
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== 'object' || !Array.isArray(value.weeks)) return null;
  const weekIds = new Set(value.weeks.map((week) => week?.id).filter(Boolean));
  const selectedWeekId = weekIds.has(value.ui?.selectedWeekId)
    ? value.ui.selectedWeekId
    : value.weeks[0]?.id || null;
  return { ui: { selectedWeekId }, weeks: value.weeks };
}

// Carry a meal's lazily-generated ingredients/nutrition/videos across an optimistic
// calendar update ONLY when the dish identity (name + servings/batch size) is
// unchanged. If it changed, drop them so the card regenerates on next open. The
// conductor re-sends the whole calendar (ingredients included) on every edit, so
// without this a servings change would keep showing the old single-serving list.
// Mirrors the backend's write-time invalidation so both views agree.
function reconcileCalendarDetails(prev, next) {
  if (!prev) return next;

  const priorMeal = (weekId, dayName, meal) => {
    const week = prev.weeks?.find((item) => item.id === weekId);
    const day = week?.days?.find((item) => item.day === dayName);
    return day?.[meal] || null;
  };

  return {
    ...next,
    weeks: next.weeks.map((week) => ({
      ...week,
      days: (week.days || []).map((day) => {
        const nextDay = { ...day };
        for (const meal of ['breakfast', 'lunch', 'dinner']) {
          const incoming = nextDay[meal];
          if (!incoming || !Array.isArray(incoming.ingredients)) continue;

          const prior = priorMeal(week.id, day.day, meal);
          const sameIdentity = prior
            && prior.name === incoming.name
            && (prior.servings || 1) === (incoming.servings || 1);
          if (!sameIdentity) {
            const { ingredients, nutrition, youtubeVideos, ...rest } = incoming;
            nextDay[meal] = rest;
          }
        }
        return nextDay;
      }),
    })),
  };
}

// Shape a show_basket tool input into our Basket state. Each item is one shopping line:
// the ingredient it fulfills, whether a product was found, and (when found) the
// product + pack count. Mirrors the backend's Basket normalization so optimistic
// (live SSE) state matches what lands on disk.
function basketFromToolInput(input) {
  let value = input;
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== 'object' || !Array.isArray(value.items)) return null;

  const items = value.items
    .map((raw) => {
      if (!raw || typeof raw !== 'object') return null;
      const ingredient = typeof raw.ingredient === 'string' ? raw.ingredient.trim() : '';
      if (!ingredient) return null;

      const item = { ingredient, status: 'not_found' };
      if (typeof raw.quantity === 'string' && raw.quantity.trim()) item.quantity = raw.quantity.trim();

      const product = raw.status === 'not_found' ? null : raw.product;
      const name = product && typeof product.name === 'string' ? product.name.trim() : '';
      if (name) {
        item.status = 'found';
        item.product = { name };
        for (const key of ['packSize', 'price', 'rating', 'imageUrl', 'productId']) {
          if (typeof product[key] === 'string' && product[key].trim()) item.product[key] = product[key].trim();
        }
        const count = Math.trunc(Number(raw.count));
        item.count = Number.isFinite(count) && count > 0 ? count : 1;
      }
      return item;
    })
    .filter(Boolean);

  return { items };
}

function isAbortError(err) {
  return err?.name === 'AbortError';
}

function shortSessionId(agentSessionId) {
  return agentSessionId ? agentSessionId.slice(0, 8) : '';
}

function agentResumeCommand(agentId, agentSessionId) {
  if (!agentSessionId) return '';
  if (agentId === 'codex') return `codex exec resume ${agentSessionId}`;
  if (agentId === 'claude') return `claude --resume ${agentSessionId}`;
  return agentSessionId;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

function imageSrc(attachment) {
  return attachment.previewUrl || apiUrl(attachment.url);
}

function AttachmentStrip({ attachments, onRemove }) {
  if (!attachments?.length) return null;

  return (
    <div className="mb-2 flex flex-wrap gap-2">
      {attachments.map((attachment) => (
        <div
          key={attachment.id || attachment.url}
          className="group relative h-16 w-16 overflow-hidden rounded-lg border border-bp-jambalaya/12 bg-bp-jambalaya/5"
          title={attachment.name}
        >
          <img
            src={imageSrc(attachment)}
            alt={attachment.name || 'Attached image'}
            className="h-full w-full object-cover"
          />
          {onRemove && (
            <button
              type="button"
              onClick={() => onRemove(attachment.id)}
              className="absolute right-1 top-1 grid h-5 w-5 place-items-center rounded-full bg-bp-jambalaya/80 text-xs leading-none text-bp-linen opacity-90 hover:bg-bp-jambalaya"
              title="Remove image"
              aria-label="Remove image"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// The main screen: top bar (New Session / History / Profile) + the chat for the
// ACTIVE session. Session state lives on the server; we just render it.
export default function Workspace({ agent, provider, onBack }) {
  const [messages, setMessages] = useState([]); // { role, text, tools?: [], activeTool?, liveStatus? }
  const [name, setName] = useState(null);
  const [sessionId, setSessionId] = useState('');
  const [agentSessionId, setAgentSessionId] = useState('');
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [activeSurface, setActiveSurface] = useState('chat');
  const [calendar, setCalendar] = useState(null);
  const [basket, setBasket] = useState(null);
  const [showProfile, setShowProfile] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showPravaCheckout, setShowPravaCheckout] = useState(false);
  const [pravaCheckoutMode, setPravaCheckoutMode] = useState('agent');
  const [showMenu, setShowMenu] = useState(false);
  const [copiedAgentSession, setCopiedAgentSession] = useState(false);
  // The opened day-detail card: { weekId, dayName, mealKey }. Ingredients/macros
  // for that day are fetched lazily the first time it opens.
  const [mealDetail, setMealDetail] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState('');
  const [buildingList, setBuildingList] = useState(false);
  // The consolidated shopping list the Basket is filled from, and whether a fill run
  // is currently in progress (blocks the composer + drives the "still finding" group).
  const [ingredientList, setIngredientList] = useState([]);
  const [filling, setFilling] = useState(false);
  // The single item currently being sourced into the Basket (its name), or null —
  // covers both promoting a pantry staple and retrying a not-found item.
  const [sourcingItem, setSourcingItem] = useState(null);
  // True while the "Buy on Swiggy" push routes the Basket into the real store cart.
  const [pushing, setPushing] = useState(false);
  const [pendingPravaHandoff, setPendingPravaHandoff] = useState(null);
  const scrollRef = useRef(null);
  const menuRef = useRef(null);
  const fileInputRef = useRef(null);
  const openingSessionIds = useRef(new Set());

  function clearAttachments() {
    setAttachments((current) => {
      current.forEach((attachment) => {
        if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      });
      return [];
    });
  }

  async function copyAgentResumeCommand() {
    const command = agentResumeCommand(agent.id, agentSessionId);
    if (!command) return;
    await navigator.clipboard?.writeText(command);
    setCopiedAgentSession(true);
    window.setTimeout(() => setCopiedAgentSession(false), 1400);
  }

  // Map a server transcript row → our render shape.
  const toMsg = (m) => (
    m.role === 'assistant'
      ? freshAssistantMessage({ text: m.content, attachments: m.attachments || [] })
      : { role: m.role, text: m.content, attachments: m.attachments || [] }
  );

  // Load the active session (server creates one if none exists).
  useEffect(() => {
    const controller = new AbortController();

    setMessages([]);
    setName(null);
    setSessionId('');
    setAgentSessionId('');
    setBusy(false);
    setStatus('');
    setActiveSurface('chat');
    setCalendar(null);
    setBasket(null);
    setMealDetail(null);
    setDetailsError('');
    setBuildingList(false);
    setIngredientList([]);
    setFilling(false);
    setSourcingItem(null);
    setPushing(false);
    clearAttachments();

    Promise.all([
      getCurrentSession({ signal: controller.signal }),
      getSessionCalendar({ signal: controller.signal }),
      getSessionBasket({ signal: controller.signal }),
      getIngredientList({ signal: controller.signal }),
    ])
      .then(([s, sessionCalendar, sessionBasket, sessionIngredientList]) => {
        if (controller.signal.aborted) return;
        setMessages(s.messages.map(toMsg));
        setName(s.name);
        setSessionId(s.sessionId || '');
        setAgentSessionId(s.agentSessionId || '');
        setActiveSurface(s.activeSurface || 'chat');
        setCalendar(sessionCalendar);
        setBasket(sessionBasket);
        setIngredientList(sessionIngredientList || []);
        if (s.messages.length === 0) startOpening(s.sessionId, controller.signal);
      })
      .catch((e) => {
        if (!isAbortError(e)) setMessages([freshAssistantMessage({ text: `Error: ${e.message}` })]);
      });

    return () => controller.abort();
  }, [agent.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, status]);

  useEffect(() => {
    if (!showMenu) return undefined;

    function closeOnOutsideClick(e) {
      if (!menuRef.current?.contains(e.target)) setShowMenu(false);
    }

    function closeOnEscape(e) {
      if (e.key === 'Escape') setShowMenu(false);
    }

    document.addEventListener('pointerdown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [showMenu]);

  async function startNew() {
    if (busy) return;
    setStatus('');
    setActiveSurface('chat');
    setCalendar(null);
    setBasket(null);
    setMealDetail(null);
    setDetailsError('');
    setBuildingList(false);
    setIngredientList([]);
    setFilling(false);
    setSourcingItem(null);
    setPushing(false);
    clearAttachments();
    try {
      const s = await newSession();
      setMessages(s.messages.map(toMsg));
      setName(s.name);
      setSessionId(s.sessionId || '');
      setAgentSessionId(s.agentSessionId || '');
      if (s.messages.length === 0) startOpening(s.sessionId);
    } catch (e) {
      setMessages((m) => [...m, freshAssistantMessage({ text: `Error: ${e.message}` })]);
    }
  }

  async function startOpening(sessionId, signal) {
    if (!sessionId || signal?.aborted || openingSessionIds.current.has(sessionId)) return;
    openingSessionIds.current.add(sessionId);
    setBusy(true);
    setStatus('');
    setMessages((m) => [
      ...m,
      freshAssistantMessage({ liveStatus: { title: 'Starting...', detail: 'Boppai is opening the conversation.' } }),
    ]);

    const patchAssistant = (fn) =>
      setMessages((m) => {
        const next = [...m];
        const assistantIndex = next.length - 1;
        next[assistantIndex] = fn(next[assistantIndex]);
        return next;
      });

    try {
      await streamOpening({
        agent: agent.id,
        signal,
        onEvent: (ev) => {
          if (signal?.aborted) return;
          switch (ev.type) {
            case 'session':
              setAgentSessionId(ev.sessionId);
              break;
            case 'status':
              setStatus('');
              patchAssistant((a) => ({
                ...a,
                liveStatus: a.activeTool ? a.liveStatus : liveStatusForLabel(ev.label),
              }));
              break;
            case 'delta':
              setStatus('');
              patchAssistant((a) => ({
                ...a,
                activeTool: null,
                liveStatus: { title: 'Writing the opener...', detail: 'More may still be coming.' },
                text: a.text + ev.text,
              }));
              break;
            case 'tool':
              setStatus('');
              applyToolInput(ev.name, ev.input);
              patchAssistant((a) => ({
                ...a,
                activeTool: ev.name,
                liveStatus: liveStatusForTool(ev.name),
                tools: [...(a.tools || []), ev.name],
              }));
              break;
            case 'error':
              patchAssistant((a) => ({
                ...a,
                activeTool: null,
                liveStatus: null,
                text: (a.text ? a.text + '\n\n' : '') + `Error: ${ev.message}`,
              }));
              break;
            default:
              break;
          }
        },
      });
    } catch (err) {
      if (isAbortError(err) || signal?.aborted) return;
      patchAssistant((a) => ({
        ...a,
        activeTool: null,
        liveStatus: null,
        text: (a.text ? a.text + '\n\n' : '') + `Error: ${err.message}`,
      }));
    } finally {
      if (signal?.aborted) return;
      patchAssistant((a) => ({ ...a, activeTool: null, liveStatus: null }));
      setBusy(false);
      setStatus('');
      getProfile().then((p) => setName(p.name)).catch(() => {});
    }
  }

  function runMenuAction(action) {
    setShowMenu(false);
    action();
  }

  function applyCalendarToolInput(input) {
    const nextCalendar = calendarFromToolInput(input);
    if (!nextCalendar) return;
    const hasWeeks = nextCalendar.weeks.length > 0;
    // Reconcile against the current in-memory calendar so a dish whose name or
    // servings changed loses its stale cached ingredients (see reconcile helper).
    setCalendar((prev) => (hasWeeks ? reconcileCalendarDetails(prev, nextCalendar) : null));
    setActiveSurface(hasWeeks ? 'calendar' : 'chat');
  }

  // Apply a show_basket tool input optimistically (live SSE), during both the fill run
  // and later conductor edits. Empty items clears the Basket back to chat.
  function applyShowBasketInput(input) {
    const nextBasket = basketFromToolInput(input);
    if (!nextBasket) return;
    setBasket({ items: nextBasket.items });
    setActiveSurface(nextBasket.items.length ? 'basket' : 'chat');
  }

  function applyToolInput(name, input) {
    if (name === 'show_chat') setActiveSurface('chat');
    if (name === 'show_calendar') applyCalendarToolInput(input);
    if (name === 'show_basket') applyShowBasketInput(input);
    if (name === 'start_prava_checkout') {
      setPravaCheckoutMode('agent');
      setShowPravaCheckout(true);
    }
  }

  async function clearDayFromCalendar({ weekId, day }) {
    if (!weekId || !day || busy) return;
    setStatus('');
    try {
      const updated = await clearCalendarDay({ weekId, day });
      setCalendar(updated?.weeks?.length ? updated : null);
      setActiveSurface(updated?.weeks?.length ? 'calendar' : 'chat');
    } catch (err) {
      setStatus(err.message);
    }
  }

  // True when every named meal on the day already has a generated ingredient list.
  function dayHasAllDetails(dayObj) {
    return ['breakfast', 'lunch', 'dinner']
      .filter((meal) => dayObj?.[meal]?.name)
      .every((meal) => Array.isArray(dayObj[meal].ingredients));
  }

  // Generate ingredients + macros for a day if they're not cached yet. Skips the
  // real agent call (and the spinner) when the day is already complete.
  async function ensureDayDetails(weekId, dayName, { force = false } = {}) {
    const week = calendar?.weeks.find((w) => w.id === weekId);
    const dayObj = week?.days.find((d) => d.day === dayName);
    if (!dayObj || (!force && dayHasAllDetails(dayObj))) return;

    setDetailsLoading(true);
    setDetailsError('');
    try {
      const updated = await generateDayDetails({ weekId, day: dayName, force });
      if (updated?.weeks?.length) setCalendar(updated);
    } catch (err) {
      setDetailsError(err.message);
    } finally {
      setDetailsLoading(false);
    }
  }

  function openMeal({ weekId, dayName, mealKey }) {
    setDetailsError('');
    setMealDetail({ weekId, dayName, mealKey });
    ensureDayDetails(weekId, dayName);
  }

  async function selectWeekFromCalendar(weekId) {
    if (!weekId || busy) return;
    setStatus('');
    try {
      const updated = await selectCalendarWeek({ weekId });
      setCalendar(updated?.weeks?.length ? updated : null);
      setActiveSurface(updated?.weeks?.length ? 'calendar' : 'chat');
    } catch (err) {
      setStatus(err.message);
    }
  }

  // "Build grocery list" on the calendar. First consolidate the whole plan into one
  // shopping list (we stay on the calendar with the FAB spinner, generating any
  // missing day details). Then redirect to the Basket and fill it live from that list.
  async function buildGroceryListNow() {
    if (buildingList || filling) return;
    setStatus('');
    setBuildingList(true);
    try {
      const { items, calendar: updated } = await buildGroceryList();
      if (updated?.weeks?.length) setCalendar(updated);
      const list = items || [];
      setIngredientList(list);
      setBuildingList(false);
      if (!list.length) {
        setStatus('No ingredients to shop for yet — plan some meals first.');
        return;
      }
      // Redirect into the Basket (empty for now) and fill it from the list.
      setBasket({ items: [] });
      setActiveSurface('basket');
      await fillBasketNow();
    } catch (err) {
      setStatus(err.message);
      setBuildingList(false);
    }
  }

  // Run the fill agent: it sources each ingredient and calls show_basket as it goes, so
  // the Basket fills in five at a time. We keep the chat quiet (the cards are the
  // feedback) and block the composer while it runs, then drop a one-line summary.
  async function fillBasketNow() {
    setFilling(true);
    let lastBasket = null;
    try {
      await streamFillBasket({
        onEvent: (ev) => {
          if (ev.type === 'tool' && ev.name === 'show_basket') {
            const parsed = basketFromToolInput(ev.input);
            if (parsed) {
              lastBasket = parsed;
              applyShowBasketInput(ev.input);
            }
          }
        },
      });
    } catch (err) {
      setStatus(err.message);
    } finally {
      setFilling(false);
      const items = lastBasket?.items || [];
      if (items.length) {
        const found = items.filter((item) => item.status === 'found').length;
        const missing = items.length - found;
        const summary = `Basket ready — ${found} found${missing ? `, ${missing} not found` : ''}.`;
        setMessages((m) => [...m, freshAssistantMessage({ text: summary })]);
      }
    }
  }

  // Direct UI edits from the Basket cards (the +/- stepper and the X).
  async function changeBasketCount(ingredient, count) {
    if (count < 1) return;
    try {
      const updated = await setBasketCount({ ingredient, count });
      if (updated) setBasket(updated);
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function removeBasketItemNow(ingredient) {
    try {
      const updated = await removeBasketItem({ ingredient });
      setBasket(updated || { items: [] });
      if (!updated?.items?.length) setActiveSurface('chat');
    } catch (err) {
      setStatus(err.message);
    }
  }

  // Source one item into the Basket on demand — promote a pantry staple (the + on a
  // staple tag) or retry a not-found item (the refetch on a not-found tag). Streams like
  // the fill: the agent searches this one item and show_basket upserts it. One at a time.
  async function sourceItem(ingredient) {
    if (filling || sourcingItem) return;
    setStatus('');
    setSourcingItem(ingredient);
    try {
      await streamSourceItem({
        ingredient,
        onEvent: (ev) => {
          if (ev.type === 'tool' && ev.name === 'show_basket') applyShowBasketInput(ev.input);
        },
      });
    } catch (err) {
      setStatus(err.message);
    } finally {
      setSourcingItem(null);
    }
  }

  // "Buy on Swiggy": route the request through the conductor instead of a separate
  // agent. We send it a plain chat turn asking it to ADD every found Basket item on
  // top of the user's real store cart (never clearing it), then read the store cart back
  // and report what was added + the total. The conductor reads basket.json itself, so we
  // only send the instruction. Staging only — it does not check out or take payment.
  async function buyOnSwiggy() {
    if (busy || filling || sourcingItem || pushing) return;
    const found = (basket?.items || []).filter((it) => it.status === 'found' && it.product?.productId);
    if (!found.length) return;
    const serviceName = provider?.name || 'grocery';
    setPushing(true);
    try {
      await runConductorTurn({
        bubbleText: `Add my Basket to my ${serviceName} cart`,
        modelMessage:
          `Add every found item in my app Basket to my ${serviceName} cart — add them on top of `
          + `whatever is already in that ${serviceName} cart, do NOT clear it. Then get my ${serviceName} cart and `
          + `tell me what was added and my total bill. Do not take payment yet — after showing my total, `
          + `end by asking if I'd like to pay with Prava.`,
      });
    } finally {
      setPushing(false);
    }
  }

  function addFiles(fileList) {
    if (!agent.supportsImages) {
      setStatus(`Image chat isn't supported for ${agent.name}.`);
      return;
    }

    const files = Array.from(fileList || []);
    if (files.length === 0) return;

    setAttachments((current) => {
      const next = [...current];
      for (const file of files) {
        if (next.length >= MAX_IMAGES) {
          setStatus(`Attach up to ${MAX_IMAGES} images at a time.`);
          break;
        }
        if (!IMAGE_TYPES.has(file.type)) {
          setStatus('Images must be PNG, JPEG, WebP, or GIF.');
          continue;
        }
        if (file.size > MAX_IMAGE_BYTES) {
          setStatus('Each image must be 8 MB or smaller.');
          continue;
        }
        next.push({
          id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
          name: file.name,
          file,
          previewUrl: URL.createObjectURL(file),
        });
      }
      return next;
    });
  }

  function removeAttachment(id) {
    setAttachments((current) => {
      const doomed = current.find((attachment) => attachment.id === id);
      if (doomed?.previewUrl) URL.revokeObjectURL(doomed.previewUrl);
      return current.filter((attachment) => attachment.id !== id);
    });
  }

  async function send() {
    const text = input.trim();
    const pendingAttachments = attachments;
    if ((!text && pendingAttachments.length === 0) || busy || filling || sourcingItem || pushing) return;
    setInput('');
    setAttachments([]);
    await runConductorTurn({
      modelMessage: text,
      bubbleText: text,
      bubbleAttachments: pendingAttachments,
      resolveImages: () =>
        Promise.all(
          pendingAttachments.map(async (attachment) => ({
            name: attachment.name,
            type: attachment.file.type,
            data: await fileToDataUrl(attachment.file),
          })),
        ),
    });
  }

  // Run one conductor (main chat) turn: push a user bubble + assistant placeholder,
  // stream the reply, and patch it in as events arrive. `bubbleText` is what the user
  // sees in chat; `modelMessage` is what the conductor actually receives — they differ
  // for button-triggered turns like "Buy on Swiggy". `resolveImages` (optional) encodes
  // any attachments to data URLs just before the request.
  async function runConductorTurn({
    modelMessage,
    bubbleText,
    bubbleAttachments = [],
    resolveImages = null,
    internalHandoff = false,
  }) {
    setBusy(true);
    setStatus('');

    const assistantIndex = messages.length + 1;
    setMessages((m) => [
      ...m,
      { role: 'user', text: bubbleText, attachments: bubbleAttachments },
      freshAssistantMessage({ liveStatus: { title: 'Connecting...', detail: 'Boppai is starting this turn.' } }),
    ]);

    const patchAssistant = (fn) =>
      setMessages((m) => {
        const next = [...m];
        next[assistantIndex] = fn(next[assistantIndex]);
        return next;
      });

    try {
      const images = resolveImages ? await resolveImages() : [];

      const streamer = internalHandoff ? streamInternalHandoff : streamChat;
      await streamer({
        agent: agent.id,
        message: modelMessage,
        transcriptMessage: bubbleText,
        images,
        onEvent: (ev) => {
          switch (ev.type) {
            case 'session':
              setAgentSessionId(ev.sessionId);
              break;
            case 'status':
              setStatus('');
              patchAssistant((a) => ({
                ...a,
                liveStatus: a.activeTool ? a.liveStatus : liveStatusForLabel(ev.label),
              }));
              break;
            case 'delta':
              setStatus('');
              patchAssistant((a) => ({
                ...a,
                activeTool: null,
                liveStatus: { title: 'Writing the reply...', detail: 'More may still be coming.' },
                text: a.text + ev.text,
              }));
              break;
            case 'tool':
              setStatus('');
              applyToolInput(ev.name, ev.input);
              patchAssistant((a) => ({
                ...a,
                activeTool: ev.name,
                liveStatus: liveStatusForTool(ev.name),
                tools: [...(a.tools || []), ev.name],
              }));
              break;
            case 'error':
              patchAssistant((a) => ({
                ...a,
                activeTool: null,
                liveStatus: null,
                text: (a.text ? a.text + '\n\n' : '') + `Error: ${ev.message}`,
              }));
              break;
            default:
              break;
          }
        },
      });
    } catch (err) {
      patchAssistant((a) => ({
        ...a,
        activeTool: null,
        liveStatus: null,
        text: (a.text ? a.text + '\n\n' : '') + `Error: ${err.message}`,
      }));
    } finally {
      patchAssistant((a) => ({ ...a, activeTool: null, liveStatus: null }));
      setBusy(false);
      setStatus('');
      // The agent may have saved/updated the profile via its tool this turn — refresh
      // the name shown in the header.
      getProfile().then((p) => setName(p.name)).catch(() => {});
    }
  }

  function buildPravaMerchantHandoffMessage({ checkout, credential }) {
    return [
      'Internal Prava merchant handoff. The Prava one-time credential is ready for the active Swiggy Instamart checkout.',
      '',
      'Use BrowserClaw now. Do not reveal the card number, CVV, or credential values in chat.',
      '',
      'Browser steps:',
      '1. Open exactly https://instamart.in/payment. Do not open the cart URL as a fallback.',
      '2. Click Add New Card.',
      '3. Fill the card form with:',
      `   Card Number: ${credential.cardNumber}`,
      `   Expiry Date (MM/YY): ${credential.expiry}`,
      `   CVV: ${credential.cvv}`,
      `   Cardholder Name: ${credential.nameOnCard || 'Prava User'}`,
      `   Card Nickname: ${credential.cardNickname || 'Prava'}`,
      '   Leave "Secure this card" unchecked if it is present.',
      '4. After filling, observe the proceed/payment button, wait 5 seconds, then observe it again.',
      '5. If the button is still loading/stuck, call report_prava_merchant_outcome with txnStatus="DECLINED".',
      '6. If the button is no longer loading, inspect the visible page state:',
      '   - clear success/progress/confirmation => report APPROVED',
      '   - clear decline/error/failure => report DECLINED',
      '   - ambiguous changed state => do not report success blindly; describe exactly what changed and ask Farhaan to review.',
      '',
      `Checkout: ${checkout?.merchantName || 'Swiggy Instamart'} Rs ${checkout?.totalAmount || credential.amountPaid || 'unknown'} ${checkout?.currency || 'INR'}`,
      `Transaction Ref: ${credential.txnRefId}`,
    ].join('\n');
  }

  function handlePravaCredentialReady(payload) {
    setPendingPravaHandoff(payload);
  }

  useEffect(() => {
    if (!pendingPravaHandoff || busy) return;
    const payload = pendingPravaHandoff;
    setPendingPravaHandoff(null);
    runConductorTurn({
      internalHandoff: true,
      modelMessage: buildPravaMerchantHandoffMessage(payload),
      bubbleText: 'Prava credential is ready. Starting the Swiggy browser handoff.',
    });
    // runConductorTurn intentionally stays outside deps; this effect is a small queue drain.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, pendingPravaHandoff]);

  const chatHeader = (
    <header className="flex items-center gap-3 border-b border-bp-jambalaya/12 bg-bp-linen/80 px-5 py-3 backdrop-blur">
        <button
          type="button"
          onClick={onBack}
          className="shrink-0 rounded-lg px-2 py-1 text-bp-domino hover:bg-bp-flamingo/10 hover:text-bp-flamingo"
          aria-label="Back to agent selection"
        >
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
        </button>
        <Soup className="h-6 w-6 shrink-0 text-bp-flamingo" aria-hidden="true" />
        <div className="mr-auto min-w-0 leading-tight">
          <div className="truncate font-['Nighty'] text-2xl leading-[0.9] text-bp-jambalaya">
            {name ? `Boppai · ${name}` : 'Boppai'}
          </div>
          <div className="mt-0.5 truncate text-xs font-medium text-bp-blue-chill">
            {agent.name} connected{agent.account ? ` · ${agent.account}` : ''}
            {provider ? ` · ${provider.name}` : ''}
          </div>
          {(sessionId || agentSessionId) && (
            <div
              className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-bp-domino/80"
              title={[
                sessionId ? `Session folder ${sessionId}` : null,
                agentSessionId ? `Agent session ${agentSessionId}` : null,
                agentSessionId ? `Copy: ${agentResumeCommand(agent.id, agentSessionId)}` : null,
              ].filter(Boolean).join(' · ')}
            >
              {sessionId && <span className="truncate">Session {shortSessionId(sessionId)}</span>}
              {agentSessionId && (
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="break-all">Agent session {agentSessionId}</span>
                  <button
                    type="button"
                    onClick={copyAgentResumeCommand}
                    className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border border-bp-domino/20 text-bp-domino/80 transition hover:border-bp-jambalaya/40 hover:text-bp-jambalaya"
                    aria-label={`Copy ${agent.name} resume command`}
                    title={`Copy ${agentResumeCommand(agent.id, agentSessionId)}`}
                  >
                    {copiedAgentSession ? (
                      <Check className="h-3 w-3" aria-hidden="true" />
                    ) : (
                      <Copy className="h-3 w-3" aria-hidden="true" />
                    )}
                  </button>
                </span>
              )}
            </div>
          )}
        </div>

        <div ref={menuRef} className="relative shrink-0">
          <button
            type="button"
            onClick={() => setShowMenu((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={showMenu}
            className="rounded-lg px-2.5 py-1.5 text-xl leading-none text-bp-domino hover:bg-bp-flamingo/10 hover:text-bp-flamingo"
            title="Open menu"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>

          {showMenu && (
            <div
              role="menu"
              className="absolute right-0 top-10 z-20 w-64 overflow-hidden rounded-xl border border-bp-jambalaya/12 bg-bp-linen py-1 text-sm shadow-[0_1rem_2.5rem_rgba(97,55,17,0.2)]"
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(startNew)}
                disabled={busy}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left font-semibold text-bp-flamingo hover:bg-bp-flamingo/8 disabled:cursor-not-allowed disabled:opacity-40"
                title="Drop this session and start fresh"
              >
                <RefreshCw className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>New session</span>
              </button>
              <div className="my-1 border-t border-bp-jambalaya/12" />
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => setShowHistory(true))}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-bp-jambalaya hover:bg-bp-flamingo/8 hover:text-bp-flamingo"
                title="Past sessions"
              >
                <Clock3 className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>History</span>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => setShowProfile(true))}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-bp-jambalaya hover:bg-bp-flamingo/8 hover:text-bp-flamingo"
                title="Your profile"
              >
                <Settings className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>Profile</span>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runMenuAction(() => setShowTools(true))}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-bp-jambalaya hover:bg-bp-flamingo/8 hover:text-bp-flamingo"
                title="Tools our MCP exposes"
              >
                <Wrench className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>Tools</span>
              </button>
            </div>
          )}
        </div>
      </header>
  );

  const messagesPanel = (
    <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-6">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div
              className={
                'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ' +
                (m.role === 'user'
                  ? 'whitespace-pre-wrap bg-bp-flamingo text-bp-linen'
                  : 'border border-bp-jambalaya/10 bg-white/80 text-bp-jambalaya')
              }
            >
              {m.tools?.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {m.tools.map((t, j) => (
                    <span
                      key={j}
                      className={
                        'rounded px-1.5 py-0.5 text-[11px] ' +
                        (m.activeTool === t
                          ? 'bg-bp-conifer/30 text-bp-jambalaya'
                          : 'bg-bp-jambalaya/8 text-bp-domino')
                      }
                    >
                      <Wrench className="mr-1 inline h-3 w-3 align-[-2px]" aria-hidden="true" />
                      {toolChipLabel(t)}
                    </span>
                  ))}
                </div>
              )}
              <AttachmentStrip attachments={m.attachments} />
              {m.role === 'assistant'
                ? m.text
                  ? (
                    <>
                      <YouTubeGallery text={m.text} />
                      <MarkdownMessage text={m.text} />
                    </>
                  )
                  : !m.liveStatus && <span className="text-bp-domino">…</span>
                : m.text}
              {m.role === 'assistant' && m.liveStatus && (
                <div
                  role="status"
                  aria-live="polite"
                  className="mt-3 flex items-center gap-4 overflow-hidden rounded-2xl bg-[radial-gradient(circle_at_50%_40%,#faa486_0%,#ef5927_55%,#c8420f_140%)] px-5 py-5 text-xs text-bp-linen"
                >
                  <span aria-hidden="true" className="grid h-44 w-44 shrink-0 place-items-center">
                    <img
                      src={thinkingImage}
                      alt=""
                      className="h-40 w-40 animate-boppai-wobble object-contain drop-shadow-[0_0.2rem_0.4rem_rgba(97,55,17,0.35)]"
                    />
                  </span>
                  <span>
                    <span className="block font-['Nighty'] text-2xl leading-tight">{m.liveStatus.title}</span>
                    <span className="text-sm text-bp-linen/80">{m.liveStatus.detail}</span>
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}

        {status && <div className="pl-1 text-xs text-bp-domino">{status}</div>}
      </div>
  );

  const composer = (
    <div className="border-t border-bp-jambalaya/12 bg-bp-linen px-5 py-3">
        <AttachmentStrip attachments={attachments} onRemove={removeAttachment} />
        <div className="flex items-end gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy || filling || Boolean(sourcingItem) || pushing || !agent.supportsImages}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-bp-jambalaya/15 text-xl leading-none text-bp-domino transition hover:border-bp-flamingo hover:bg-bp-flamingo/8 hover:text-bp-flamingo disabled:cursor-not-allowed disabled:opacity-40"
            title={agent.supportsImages ? 'Attach image' : `Image chat isn't supported for ${agent.name}`}
            aria-label="Attach image"
          >
            <ImagePlus className="h-5 w-5" aria-hidden="true" />
          </button>
          <textarea
            rows={1}
            value={input}
            disabled={filling || Boolean(sourcingItem) || pushing}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={filling ? 'Filling your basket…' : sourcingItem ? 'Adding to basket…' : pushing ? 'Sending to Swiggy…' : 'Message Boppai…'}
            className="max-h-40 flex-1 resize-none rounded-xl border border-bp-jambalaya/15 bg-white px-4 py-2.5 text-sm text-bp-jambalaya outline-none placeholder:text-bp-domino focus:border-bp-flamingo focus:ring-2 focus:ring-bp-geraldine/30 disabled:cursor-not-allowed disabled:bg-bp-jambalaya/5"
          />
          <button
            type="button"
            onClick={send}
            disabled={busy || filling || Boolean(sourcingItem) || pushing || (!input.trim() && attachments.length === 0)}
            className="inline-flex h-10 items-center justify-center rounded-full bg-bp-flamingo px-6 pb-1 pt-1.5 font-['Nighty'] text-2xl leading-none text-bp-linen shadow-[0_0.6rem_1.4rem_rgba(97,55,17,0.18)] transition-colors duration-200 hover:bg-bp-jambalaya focus:outline-none focus-visible:ring-4 focus-visible:ring-bp-geraldine/45 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? '…' : 'Send'}
          </button>
        </div>
    </div>
  );

  // The Basket surface stays up while a fill is running even before any card lands (so
  // the "still finding" group shows from the first moment), and whenever there's an
  // ingredient list to show — a plan that's all pantry staples has an empty basket.json
  // but should still show its staple tags.
  const basketActive = Boolean(basket?.items?.length) || filling
    || (activeSurface === 'basket' && ingredientList.length > 0);
  const visibleSurface = (
    activeSurface === 'basket' && basketActive
      ? 'basket'
      : activeSurface === 'calendar' && calendar?.weeks?.length
        ? 'calendar'
        : 'chat'
  );

  return (
    <div
      className={
        visibleSurface !== 'chat'
          ? 'mx-auto flex h-screen w-full max-w-[1600px] p-3'
          : 'mx-auto flex h-screen max-w-2xl flex-col'
      }
    >
      {/* Paper-grain texture layer: fixed to the viewport, behind everything,
          so the linen page (and the chat gutters) feel like warm paper. */}
      <div aria-hidden="true" className="bp-paper-grain pointer-events-none fixed inset-0 -z-10 opacity-[0.06]" />

      {visibleSurface !== 'chat' ? (
        <>
          <section className="flex min-w-0 flex-[7] flex-col overflow-hidden rounded-l-lg border border-r-0 border-bp-jambalaya/12 bg-bp-linen">
            <div className="min-h-0 flex-1 p-3">
              {visibleSurface === 'basket' ? (
                <BasketBoard
                  items={basket?.items || []}
                  ingredientList={ingredientList}
                  filling={filling}
                  sourcingItem={sourcingItem}
                  pushing={pushing}
                  onSetCount={changeBasketCount}
                  onRemove={removeBasketItemNow}
                  onSourceItem={sourceItem}
                  onBuyOnSwiggy={buyOnSwiggy}
                />
              ) : (
                <MealPlannerCalendar
                  weeks={calendar.weeks}
                  selectedWeekId={calendar.ui?.selectedWeekId}
                  onWeekChange={selectWeekFromCalendar}
                  onClearDay={clearDayFromCalendar}
                  onOpenMeal={openMeal}
                  onBuildGroceryList={buildGroceryListNow}
                  buildingList={buildingList}
                />
              )}
            </div>
          </section>

          <section className="flex min-w-80 flex-[3] flex-col overflow-hidden rounded-r-lg border border-bp-jambalaya/12 border-l-bp-jambalaya/8 bg-bp-linen">
            {chatHeader}
            {messagesPanel}
            {composer}
          </section>
        </>
      ) : (
        <>
          {chatHeader}
          {messagesPanel}
          {composer}
        </>
      )}

      {visibleSurface === 'calendar' && mealDetail && (() => {
        const week = calendar?.weeks.find((w) => w.id === mealDetail.weekId);
        const dayObj = week?.days.find((d) => d.day === mealDetail.dayName);
        if (!dayObj) return null;
        const existingMeals = ['breakfast', 'lunch', 'dinner'].filter((meal) => dayObj[meal]?.name);
        if (!existingMeals.includes(mealDetail.mealKey)) return null;
        return (
          <MealDetailModal
            dayName={mealDetail.dayName}
            day={dayObj}
            existingMeals={existingMeals}
            mealKey={mealDetail.mealKey}
            loading={detailsLoading}
            error={detailsError}
            onRetry={(options) => ensureDayDetails(mealDetail.weekId, mealDetail.dayName, options)}
            onMealChange={(mealKey) => setMealDetail((current) => ({ ...current, mealKey }))}
            onClose={() => { setMealDetail(null); setDetailsError(''); }}
          />
        );
      })()}

      {showProfile && (
        <ProfileModal onClose={() => setShowProfile(false)} onSaved={() => getProfile().then((p) => setName(p.name))} />
      )}
      {showHistory && <HistoryModal onClose={() => setShowHistory(false)} />}
      {showTools && <ToolsModal onClose={() => setShowTools(false)} />}
      {showPravaCheckout && (
        <PravaCheckoutModal
          mode={pravaCheckoutMode}
          onClose={() => setShowPravaCheckout(false)}
          onCredentialReady={handlePravaCredentialReady}
        />
      )}
    </div>
  );
}
