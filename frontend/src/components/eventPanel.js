/**
 * EventPanel Component - Scrollable panel showing AI analysis results.
 */

import { icon } from '../icons.js';
import { translateAnalysisEvents } from '../api.js';
import {
  formatNumber,
  formatRelativeClock,
  formatTimeOfDay,
  formatVideoTime,
  getLanguage,
  t,
} from '../i18n.js';

const EVENT_FILTER_STORAGE_KEY = 'phylax-event-panel-filter';
const EVENT_TRANSLATION_CACHE_VERSION = 'v4';
const translationCache = new Map();

const EVENT_FILTERS = [
  { id: 'all', iconName: 'layers' },
  { id: 'person', iconName: 'user' },
  { id: 'vehicle', iconName: 'car' },
  { id: 'motion', iconName: 'activity' },
  { id: 'anomaly', iconName: 'alertTriangle' },
  { id: 'normal', iconName: 'checkCircle' },
  { id: 'waived', iconName: 'checkCircle' },
];

function formatPanelTime(sec) {
  if (sec > 1e7) {
    return formatRelativeClock(sec);
  }
  return formatVideoTime(sec);
}

function getEventTypeIcon(eventType) {
  const map = {
    motion: 'activity',
    person: 'user',
    vehicle: 'car',
    anomaly: 'alertTriangle',
    normal: 'checkCircle',
    Normal: 'checkCircle',
    warning: 'alertTriangle',
    Warning: 'alertTriangle',
    emergency: 'zap',
    Emergency: 'zap',
    none: 'eye',
  };
  return map[eventType] || 'eye';
}

function getEventTypeLabel(eventType) {
  const normalized = String(eventType || 'none').toLowerCase();
  const label = t(`eventPanel.filters.${normalized}`);
  return label === `eventPanel.filters.${normalized}` ? normalized : label;
}

function getSavedFilter() {
  try {
    const saved = localStorage.getItem(EVENT_FILTER_STORAGE_KEY);
    return EVENT_FILTERS.some((filter) => filter.id === saved) ? saved : 'all';
  } catch {
    return 'all';
  }
}

function saveFilter(filterId) {
  try {
    localStorage.setItem(EVENT_FILTER_STORAGE_KEY, filterId);
  } catch {
    // Ignore persistence failures.
  }
}

function matchesFilter(event, filterId) {
  if (filterId === 'all') return true;
  if (filterId === 'waived') return !!event.is_waived || !!event.is_error;
  return String(event.event_type || 'none').toLowerCase() === filterId;
}

function getFilterCount(events, filterId) {
  return events.filter((event) => matchesFilter(event, filterId)).length;
}

function getFilterLabel(filterId) {
  return t(`eventPanel.filters.${filterId}`) || t('eventPanel.selected');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function eventTranslationId(event) {
  return String(event.id ?? `${event.timestamp_sec || ''}-${event.event_type || ''}`);
}

function translationCacheKey(language, event) {
  return [
    EVENT_TRANSLATION_CACHE_VERSION,
    language,
    eventTranslationId(event),
    event.summary || '',
    event.description || '',
    event.frame_observation || '',
    event.temporal_assessment || '',
    event.anomaly_rationale || '',
    normalizeList(event.changes_detected).join('||'),
  ].join('|');
}

function applyLocalTranslationFallback(event, language) {
  if (language !== 'zh') return event;
  return {
    ...event,
    summary: translateCommonEventText(event.summary || '', language),
    description: translateCommonEventText(event.description || '', language),
    frame_observation: translateCommonEventText(event.frame_observation || '', language),
    temporal_assessment: translateCommonEventText(event.temporal_assessment || '', language),
    anomaly_rationale: translateCommonEventText(event.anomaly_rationale || '', language),
    changes_detected: normalizeList(event.changes_detected).map((item) => translateCommonEventText(item, language)),
  };
}

function prepareDisplayEvent(event, language) {
  if (!language || language === 'en') return event;

  const cached = translationCache.get(translationCacheKey(language, event));
  if (cached) {
    if (translatedPayloadNeedsLocalization(cached, language)) {
      translationCache.delete(translationCacheKey(language, event));
    } else {
      return {
        ...event,
        summary: cached.summary,
        description: cached.description,
        frame_observation: cached.frame_observation,
        temporal_assessment: cached.temporal_assessment,
        anomaly_rationale: cached.anomaly_rationale,
        changes_detected: cached.changes_detected,
      };
    }
  }

  const fallback = applyLocalTranslationFallback(event, language);
  return eventNeedsLocalization(fallback, language)
    ? makePendingLocalizedEvent(fallback, language)
    : fallback;
}

function makePendingLocalizedEvent(event, language) {
  return {
    ...event,
    summary: localPendingText(language, 'summary'),
    description: localPendingText(language, 'description'),
    frame_observation: '',
    temporal_assessment: '',
    anomaly_rationale: '',
    changes_detected: [],
    keywords: [],
    __translation_pending: true,
  };
}

function makeFallbackLocalizedEvent(event, language) {
  return {
    ...event,
    summary: localFallbackText(language, 'summary', event),
    description: localFallbackText(language, 'description', event),
    frame_observation: '',
    temporal_assessment: '',
    anomaly_rationale: '',
    changes_detected: [],
    keywords: normalizeList(event.keywords).map(localizeKeyword),
    __translation_fallback: true,
  };
}

function localPendingText(language, key) {
  const messages = {
    zh: {
      summary: '正在整理事件說明...',
      description: '正在以目前語言更新這筆即時分析。',
    },
    es: {
      summary: 'Preparando la descripción del evento...',
      description: 'Actualizando este análisis en el idioma actual.',
    },
    fr: {
      summary: 'Préparation de la description de l’événement...',
      description: 'Mise à jour de cette analyse dans la langue actuelle.',
    },
    ja: {
      summary: 'イベント説明を準備しています...',
      description: '現在の言語でこのリアルタイム分析を更新しています。',
    },
    ko: {
      summary: '이벤트 설명을 준비하는 중...',
      description: '현재 언어로 이 실시간 분석을 업데이트하고 있습니다.',
    },
  };
  return messages[language]?.[key] || messages.en?.[key] || 'Preparing event description...';
}

function localFallbackText(language, key, event) {
  const type = getEventTypeLabel(event.event_type);
  const messages = {
    zh: {
      summary: `已收到${type || '事件'}分析。`,
      description: '這筆即時分析的完整翻譯暫時無法完成，系統會在下一輪更新時重新整理。',
    },
    es: {
      summary: `Análisis de ${type || 'evento'} recibido.`,
      description: 'La traducción completa de este análisis aún no está lista; se actualizará en la próxima ronda.',
    },
    fr: {
      summary: `Analyse ${type || 'd’événement'} reçue.`,
      description: 'La traduction complète de cette analyse n’est pas encore prête ; elle sera mise à jour au prochain passage.',
    },
    ja: {
      summary: `${type || 'イベント'}分析を受信しました。`,
      description: 'この分析の完全な翻訳はまだ準備できていません。次回の更新で再整理されます。',
    },
    ko: {
      summary: `${type || '이벤트'} 분석을 받았습니다.`,
      description: '이 분석의 전체 번역은 아직 준비되지 않았으며 다음 업데이트에서 다시 정리됩니다.',
    },
  };
  return messages[language]?.[key] || 'Event analysis received.';
}

function translationRequestForEvent(event) {
  return {
    id: eventTranslationId(event),
    summary: event.summary || '',
    description: [
      event.description || '',
      event.frame_observation ? `[[frame_observation]] ${event.frame_observation}` : '',
      event.temporal_assessment ? `[[temporal_assessment]] ${event.temporal_assessment}` : '',
      event.anomaly_rationale ? `[[anomaly_rationale]] ${event.anomaly_rationale}` : '',
      normalizeList(event.changes_detected).map((item) => `[[change]] ${item}`).join('\n'),
    ].filter(Boolean).join('\n'),
  };
}

function cacheTranslatedEvent(originalEvent, translated, language, cachedTranslations) {
  if (translatedPayloadNeedsLocalization(translated, language)) return false;
  translationCache.set(translationCacheKey(language, originalEvent), translated);
  cachedTranslations.set(eventTranslationId(originalEvent), translated);
  return true;
}

function cacheFallbackEvent(originalEvent, language, cachedTranslations) {
  const fallback = makeFallbackLocalizedEvent(originalEvent, language);
  const translated = {
    summary: fallback.summary,
    description: fallback.description,
    frame_observation: '',
    temporal_assessment: '',
    anomaly_rationale: '',
    changes_detected: [],
  };
  cachedTranslations.set(eventTranslationId(originalEvent), translated);
}

function translateCommonEventText(text, language) {
  if (language !== 'zh' || !text) return text;

  let translated = String(text);
  const exactMap = new Map([
    ['Routine vehicle traffic observed.', '觀察到例行車流。'],
    ['Routine vehicle traffic observed on a road.', '道路上觀察到例行車流。'],
    ['Routine highway traffic observed.', '觀察到例行高速公路車流。'],
    ['Routine traffic flow on a highway.', '高速公路上為例行車流。'],
    ['Heavy routine traffic flow on a highway.', '高速公路上車流繁忙但屬例行狀況。'],
    ['Normal highway traffic.', '高速公路交通正常。'],
    ['Object detection saw: 5 cars', '物件偵測看到：5 輛車。'],
    ['Object detection only: Object detection saw: 5 cars', '僅物件偵測：物件偵測看到 5 輛車。'],
    ['Road view showing traffic flow on a multi-lane road.', '道路畫面顯示多車道道路上的車流。'],
    ['Traffic on a multi-lane highway viewed from an overpass.', '從天橋視角可見多車道高速公路車流。'],
    ['A low-resolution view of heavy traffic flowing on a multi-lane highway.', '低解析度畫面顯示多車道高速公路上車流繁忙。'],
    ['The scene represents standard, expected traffic patterns for this location.', '這個畫面呈現此地點常見且正常的交通型態。'],
    ['Moderate traffic, dominated by several motorcycles crossing or waiting at the intersection.', '畫面中為中等車流，主要是數台機車在路口穿越或等候。'],
    ['No visible accidents, blocked paths, or unexpected hazards are present.', '未見事故、道路阻塞或其他異常危害。'],
    ['Reference frame near the current playback point.', '目前播放位置附近的參考畫面。'],
    ['Reference frame selected near the current playback point.', '已選取目前播放位置附近的參考畫面。'],
  ]);

  if (exactMap.has(translated.trim())) {
    return exactMap.get(translated.trim());
  }

  translated = translated
    .replace(/Object detection only:\s*/gi, '僅物件偵測：')
    .replace(/Object detection saw:\s*(\d+)\s+cars?/gi, '物件偵測看到：$1 輛車')
    .replace(/Routine highway traffic observed\.?/gi, '觀察到例行高速公路車流。')
    .replace(/Routine vehicle traffic observed(?: on a road)?\.?/gi, '觀察到例行車流。')
    .replace(/Routine urban traffic observed\.?/gi, '觀察到市區例行車流。')
    .replace(/Routine urban vehicle traffic observed\.?/gi, '觀察到市區例行車流。')
    .replace(/Normal highway traffic\.?/gi, '高速公路交通正常。')
    .replace(/The scene represents standard, expected traffic patterns for this location\.?/gi, '這個畫面呈現此地點常見且正常的交通型態。')
    .replace(/Moderate traffic, dominated by several motorcycles crossing or waiting at the intersection\.?/gi, '畫面中為中等車流，主要是數台機車在路口穿越或等候。')
    .replace(/No visible accidents, blocked paths, or unexpected hazards are present\.?/gi, '未見事故、道路阻塞或其他異常危害。')
    .replace(/Compared with prior results/gi, '與先前結果比較')
    .replace(/Current frame/gi, '當前幀觀察')
    .replace(/Score rationale/gi, '分數理由')
    .replace(/Reference frame near the current playback point\.?/gi, '目前播放位置附近的參考畫面。')
    .replace(/Reference frame selected near the current playback point\.?/gi, '已選取目前播放位置附近的參考畫面。')
    .replace(/multi-lane highway/gi, '多車道高速公路')
    .replace(/multi-lane road/gi, '多車道道路')
    .replace(/urban/gi, '市區')
    .replace(/intersection/gi, '路口')
    .replace(/motorcycles/gi, '機車')
    .replace(/motorcycle/gi, '機車')
    .replace(/observed/gi, '觀察到')
    .replace(/routine/gi, '例行')
    .replace(/standard/gi, '標準')
    .replace(/expected/gi, '常見')
    .replace(/scene/gi, '畫面')
    .replace(/heavy traffic/gi, '繁忙車流')
    .replace(/moderate traffic/gi, '中等車流')
    .replace(/traffic flow/gi, '車流')
    .replace(/traffic patterns/gi, '交通型態')
    .replace(/vehicles?/gi, '車輛')
    .replace(/cars?/gi, '車輛');

  return translated;
}

function localLabel(key) {
  const language = getLanguage();
  const labelSets = {
    en: {
      score: 'Anomaly score',
      attention: 'Needs attention',
      routine: 'Routine',
      frameObservation: 'Current frame',
      temporalAssessment: 'Compared with prior results',
      anomalyRationale: 'Score rationale',
      gemmaChanges: 'Gemma observations',
      keywords: 'Keywords',
      yes: 'Yes',
      no: 'No',
    },
    zh: {
      score: '異常分數',
      attention: '需要注意',
      routine: '例行狀況',
      frameObservation: '當前幀觀察',
      temporalAssessment: '與先前結果比較',
      anomalyRationale: '分數理由',
      gemmaChanges: '模型觀察',
      keywords: '關鍵字',
      yes: '是',
      no: '否',
    },
    es: {
      score: 'Puntuación de anomalía',
      attention: 'Requiere atención',
      routine: 'Rutina',
      frameObservation: 'Fotograma actual',
      temporalAssessment: 'Comparación con resultados previos',
      anomalyRationale: 'Motivo de la puntuación',
      gemmaChanges: 'Observaciones del modelo',
      keywords: 'Palabras clave',
      yes: 'Sí',
      no: 'No',
    },
    fr: {
      score: "Score d'anomalie",
      attention: 'Attention requise',
      routine: 'Routine',
      frameObservation: 'Image actuelle',
      temporalAssessment: 'Comparaison avec les résultats précédents',
      anomalyRationale: 'Justification du score',
      gemmaChanges: 'Observations du modèle',
      keywords: 'Mots-clés',
      yes: 'Oui',
      no: 'Non',
    },
    ja: {
      score: '異常スコア',
      attention: '注意が必要',
      routine: '通常',
      frameObservation: '現在のフレーム',
      temporalAssessment: '前回結果との比較',
      anomalyRationale: 'スコアの理由',
      gemmaChanges: 'モデルの観察',
      keywords: 'キーワード',
      yes: 'はい',
      no: 'いいえ',
    },
    ko: {
      score: '이상 점수',
      attention: '주의 필요',
      routine: '일반',
      frameObservation: '현재 프레임',
      temporalAssessment: '이전 결과와 비교',
      anomalyRationale: '점수 근거',
      gemmaChanges: '모델 관찰',
      keywords: '키워드',
      yes: '예',
      no: '아니요',
    },
  };
  const labels = labelSets[language] || labelSets.en;
  return labels[key] || key;
}

function localizeKeyword(keyword) {
  const language = getLanguage();
  if (language === 'en') return keyword;

  const normalized = String(keyword || '').trim().toLowerCase().replaceAll('_', ' ');
  if (!normalized) return keyword;

  const dictionaries = {
    zh: {
      highway: '高速公路',
      traffic: '交通',
      routine: '例行',
      normal: '正常',
      vehicle: '車輛',
      vehicles: '車輛',
      car: '汽車',
      cars: '汽車',
      motorcycle: '機車',
      motorcycles: '機車',
      night: '夜間',
      nighttime: '夜間',
      evening: '傍晚',
      wet: '潮濕',
      road: '道路',
      interchange: '交流道',
      intersection: '路口',
      entrance: '入口',
      flow: '流量',
      stable: '穩定',
      moderate: '中等',
      heavy: '繁忙',
      dense: '密集',
      'high volume': '高流量',
      'high-volume': '高流量',
      urban: '市區',
      person: '人物',
      motion: '動態',
      anomaly: '異常',
    },
    es: {
      highway: 'autopista',
      traffic: 'tráfico',
      routine: 'rutina',
      normal: 'normal',
      vehicle: 'vehículo',
      vehicles: 'vehículos',
      car: 'auto',
      cars: 'autos',
      motorcycle: 'motocicleta',
      motorcycles: 'motocicletas',
      night: 'noche',
      nighttime: 'noche',
      evening: 'tarde',
      wet: 'mojado',
      road: 'carretera',
      interchange: 'intercambiador',
      intersection: 'intersección',
      entrance: 'entrada',
      flow: 'flujo',
      stable: 'estable',
      moderate: 'moderado',
      heavy: 'intenso',
      dense: 'denso',
      'high volume': 'alto volumen',
      'high-volume': 'alto volumen',
      urban: 'urbano',
      person: 'persona',
      motion: 'movimiento',
      anomaly: 'anomalía',
    },
    fr: {
      highway: 'autoroute',
      traffic: 'trafic',
      routine: 'routine',
      normal: 'normal',
      vehicle: 'véhicule',
      vehicles: 'véhicules',
      car: 'voiture',
      cars: 'voitures',
      motorcycle: 'moto',
      motorcycles: 'motos',
      night: 'nuit',
      nighttime: 'nuit',
      evening: 'soirée',
      wet: 'humide',
      road: 'route',
      interchange: 'échangeur',
      intersection: 'intersection',
      entrance: 'entrée',
      flow: 'flux',
      stable: 'stable',
      moderate: 'modéré',
      heavy: 'dense',
      dense: 'dense',
      'high volume': 'volume élevé',
      'high-volume': 'volume élevé',
      urban: 'urbain',
      person: 'personne',
      motion: 'mouvement',
      anomaly: 'anomalie',
    },
    ja: {
      highway: '高速道路',
      traffic: '交通',
      routine: '通常',
      normal: '正常',
      vehicle: '車両',
      vehicles: '車両',
      car: '車',
      cars: '車',
      motorcycle: 'バイク',
      motorcycles: 'バイク',
      night: '夜間',
      nighttime: '夜間',
      evening: '夕方',
      wet: '濡れた路面',
      road: '道路',
      interchange: 'インターチェンジ',
      intersection: '交差点',
      entrance: '入口',
      flow: '流れ',
      stable: '安定',
      moderate: '中程度',
      heavy: '高密度',
      dense: '高密度',
      'high volume': '交通量が多い',
      'high-volume': '交通量が多い',
      urban: '市街地',
      person: '人物',
      motion: '動き',
      anomaly: '異常',
    },
    ko: {
      highway: '고속도로',
      traffic: '교통',
      routine: '일반',
      normal: '정상',
      vehicle: '차량',
      vehicles: '차량',
      car: '자동차',
      cars: '자동차',
      motorcycle: '오토바이',
      motorcycles: '오토바이',
      night: '야간',
      nighttime: '야간',
      evening: '저녁',
      wet: '젖은 노면',
      road: '도로',
      interchange: '나들목',
      intersection: '교차로',
      entrance: '입구',
      flow: '흐름',
      stable: '안정적',
      moderate: '보통',
      heavy: '혼잡',
      dense: '밀집',
      'high volume': '교통량 많음',
      'high-volume': '교통량 많음',
      urban: '도심',
      person: '사람',
      motion: '움직임',
      anomaly: '이상',
    },
  };

  return dictionaries[language]?.[normalized] || keyword;
}

function normalizeList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean);
  }
  if (typeof value === 'string') {
    return value.split(',').map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function eventNeedsLocalization(event, language) {
  return textNeedsLocalization(
    [
      event.summary || '',
      event.description || '',
      event.frame_observation || '',
      event.temporal_assessment || '',
      event.anomaly_rationale || '',
      normalizeList(event.changes_detected).join(' '),
    ].filter(Boolean).join(' '),
    language,
  );
}

function translatedPayloadNeedsLocalization(payload, language) {
  return textNeedsLocalization(
    [
      payload.summary || '',
      payload.description || '',
      payload.frame_observation || '',
      payload.temporal_assessment || '',
      payload.anomaly_rationale || '',
      normalizeList(payload.changes_detected).join(' '),
    ].filter(Boolean).join(' '),
    language,
  );
}

function textNeedsLocalization(text, language) {
  const value = String(text || '').trim();
  if (!value) return false;
  if (language === 'en') return containsCjk(value);
  if (['zh', 'ja', 'ko'].includes(language)) {
    return textNeedsCjkLanguageCleanup(value, language);
  }
  if (['es', 'fr'].includes(language)) {
    return textNeedsLatinLanguageCleanup(value, language);
  }
  return containsCjk(value);
}

function containsHan(text) {
  return /[\u3400-\u4dbf\u4e00-\u9fff]/.test(String(text || ''));
}

function containsKana(text) {
  return /[\u3040-\u30ff]/.test(String(text || ''));
}

function containsHangul(text) {
  return /[\uac00-\ud7af]/.test(String(text || ''));
}

function containsCjk(text) {
  return /[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/.test(String(text || ''));
}

function textNeedsCjkLanguageCleanup(text, language) {
  const value = String(text || '');
  const hasEnglish = /[A-Za-z]{2,}/.test(value);
  if (language === 'zh') {
    return hasEnglish || containsKana(value) || containsHangul(value) || !containsHan(value);
  }
  if (language === 'ja') {
    return hasEnglish || containsHangul(value) || !(containsHan(value) || containsKana(value));
  }
  if (language === 'ko') {
    return hasEnglish || containsKana(value) || !containsHangul(value);
  }
  return hasEnglish;
}

function textNeedsLatinLanguageCleanup(text, language) {
  const value = String(text || '');
  if (containsCjk(value)) return true;
  const asciiWords = value.match(/\b[A-Za-z]{3,}\b/g) || [];
  if (!asciiWords.length) return false;

  const commonEnglish = new Set([
    'the', 'this', 'that', 'with', 'without', 'traffic', 'vehicle', 'vehicles',
    'routine', 'normal', 'highway', 'road', 'flow', 'continues', 'stable',
    'observed', 'scene', 'frame', 'previous', 'results', 'score', 'rationale',
    'moderate', 'heavy', 'entrance', 'intersection', 'interchange',
  ]);
  const targetMarkers = {
    es: new Set([
      'con', 'sin', 'trafico', 'tráfico', 'vehiculo', 'vehículo', 'vehiculos',
      'vehículos', 'carretera', 'flujo', 'normal', 'estable', 'observado',
      'continua', 'continúa', 'entrada', 'interseccion', 'intersección',
    ]),
    fr: new Set([
      'avec', 'sans', 'trafic', 'vehicule', 'véhicule', 'vehicules', 'véhicules',
      'route', 'flux', 'normal', 'stable', 'observe', 'observé', 'continue',
      'entree', 'entrée', 'intersection',
    ]),
  }[language] || new Set();

  const lowered = new Set(asciiWords.map((word) => word.toLowerCase()));
  return [...lowered].some((word) => commonEnglish.has(word))
    && ![...lowered].some((word) => targetMarkers.has(word));
}

function buildGemmaDetails(event) {
  const changes = normalizeList(event.changes_detected).slice(0, 4);
  const keywords = normalizeList(event.keywords).slice(0, 6);
  const frameObservation = String(event.frame_observation || '').trim();
  const temporalAssessment = String(event.temporal_assessment || '').trim();
  const anomalyRationale = String(event.anomaly_rationale || '').trim();
  const hasScore = Number.isFinite(Number(event.anomaly_score)) && Number(event.anomaly_score) > 0;
  const hasAttention = !!event.requires_attention;
  const hasDetails = (
    frameObservation ||
    temporalAssessment ||
    anomalyRationale ||
    changes.length ||
    keywords.length ||
    hasScore ||
    hasAttention
  );
  if (!hasDetails) return '';

  const score = Math.max(0, Math.min(100, Number(event.anomaly_score || 0)));
  const attentionText = hasAttention ? localLabel('yes') : localLabel('no');
  const detailRows = [
    ['frameObservation', frameObservation],
    ['temporalAssessment', temporalAssessment],
    ['anomalyRationale', anomalyRationale],
  ].filter(([, value]) => value);

  return `
    <div class="event-gemma-details">
      <div class="event-gemma-meta">
        <span>${icon('activity', 12)} ${localLabel('score')}: ${score}/100</span>
        <span>${icon(hasAttention ? 'alertTriangle' : 'checkCircle', 12)} ${hasAttention ? localLabel('attention') : localLabel('routine')}: ${attentionText}</span>
      </div>
      ${detailRows.map(([labelKey, value]) => `
        <div class="event-gemma-section">
          <div class="event-gemma-label">${localLabel(labelKey)}</div>
          <div class="event-description">${escapeHtml(translateCommonEventText(value, getLanguage()))}</div>
        </div>
      `).join('')}
      ${changes.length ? `
        <div class="event-gemma-section">
          <div class="event-gemma-label">${localLabel('gemmaChanges')}</div>
          <ul class="event-gemma-list">
            ${changes.map((change) => `<li>${escapeHtml(translateCommonEventText(change, getLanguage()))}</li>`).join('')}
          </ul>
        </div>
      ` : ''}
      ${keywords.length ? `
        <div class="event-keywords" aria-label="${localLabel('keywords')}">
          ${keywords.map((keyword) => `<span>${escapeHtml(localizeKeyword(keyword))}</span>`).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function createEventItem(event, index, panel, onEventClick) {
  const item = document.createElement('div');
  item.className = `event-item ${event.is_waived ? 'event-item-waived' : ''} ${event.is_error ? 'event-item-error' : ''}`;
  item.id = `event-item-${event.id}`;
  item.dataset.index = index;

  const reviewBadge = event.is_error
    ? `<span class="event-type-badge event-type-anomaly">${t('eventPanel.aiNotice')}</span>`
    : event.is_waived
      ? `<span class="event-type-badge event-type-normal">${t('eventPanel.filters.waived')}</span>`
      : '';

  const summary = event.summary || (event.is_waived ? t('eventPanel.routineScene') : t('eventPanel.analysisEvent'));

  item.innerHTML = `
    <div class="event-timestamp">
      ${icon('clock', 14)} ${formatPanelTime(event.timestamp_sec)}
      <span class="event-type-badge event-type-${event.event_type || 'none'}">
        ${icon(getEventTypeIcon(event.event_type), 12)} ${getEventTypeLabel(event.event_type)}
      </span>
      ${reviewBadge}
    </div>
    <div class="event-summary">${escapeHtml(summary)}</div>
    <div class="event-description">${escapeHtml(event.description || '')}</div>
    ${buildGemmaDetails(event)}
  `;

  if (onEventClick) {
    item.addEventListener('click', () => {
      panel.querySelectorAll('.event-item').forEach((element) => element.classList.remove('active'));
      item.classList.add('active');
      onEventClick(event);
    });
  }

  return item;
}

export function createEventPanel(events, onEventClick = null, aiActive = false, currentAnalyzingTs = null) {
  const panel = document.createElement('div');
  panel.className = 'event-panel';
  panel.id = 'event-panel';
  let activeFilter = getSavedFilter();
  const language = getLanguage();
  let displayEvents = events.map((event) => prepareDisplayEvent(event, language));

  const header = document.createElement('div');
  header.className = 'event-panel-header';
  header.innerHTML = `
    <div class="event-panel-title">
      ${icon('layers', 18)} ${t('eventPanel.title')}
    </div>
    <span class="event-count-badge">${t('eventPanel.count', { count: formatNumber(events.length) })}</span>
  `;
  panel.appendChild(header);

  const countBadge = header.querySelector('.event-count-badge');

  if (aiActive) {
    const statusBar = document.createElement('div');
    statusBar.className = 'ai-status-bar';
    statusBar.style.padding = '8px 16px';
    statusBar.style.borderBottom = '1px solid var(--border-color)';
    statusBar.style.fontSize = 'var(--font-size-xs)';
    statusBar.style.display = 'flex';
    statusBar.style.alignItems = 'center';
    statusBar.style.gap = '8px';

    if (currentAnalyzingTs) {
      const elapsedSec = (Date.now() / 1000) - currentAnalyzingTs;
      const percent = Math.min(99, Math.max(0, Math.floor((elapsedSec / 120) * 100)));
      statusBar.innerHTML = `
        <span style="animation: spin 1s linear infinite; display:inline-flex;">${icon('clock', 14)}</span>
        <span>${t('eventPanel.analyzingFrame', { time: formatTimeOfDay(currentAnalyzingTs), percent })}</span>
      `;
      statusBar.style.backgroundColor = 'rgba(255, 61, 61, 0.08)';
      statusBar.style.color = 'var(--text-primary)';
    } else {
      statusBar.innerHTML = `
        ${icon('clock', 14)}
        <span>${t('eventPanel.aiWaiting')}</span>
      `;
      statusBar.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
      statusBar.style.color = 'var(--text-secondary)';
    }

    panel.appendChild(statusBar);
  }

  if (events.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';

    if (aiActive) {
      empty.innerHTML = `
        <div class="empty-state-icon" style="animation: pulse 2s infinite; color:var(--accent-primary);">${icon('activity', 48)}</div>
        <div class="empty-state-title" style="color:var(--accent-primary)">${t('eventPanel.aiProgressTitle')}</div>
        <div class="empty-state-desc">${t('eventPanel.aiProgressDesc')}</div>
      `;
    } else {
      empty.innerHTML = `
        <div class="empty-state-icon">${icon('search', 48)}</div>
        <div class="empty-state-title">${t('eventPanel.noEventsTitle')}</div>
        <div class="empty-state-desc">${t('eventPanel.noEventsDesc')}</div>
      `;
    }
    panel.appendChild(empty);
    return panel;
  }

  const filterBar = document.createElement('div');
  filterBar.className = 'event-filter-bar';
  filterBar.innerHTML = EVENT_FILTERS.map((filter) => `
    <button
      type="button"
      class="event-filter-chip ${activeFilter === filter.id ? 'active' : ''}"
      data-filter="${filter.id}"
      aria-pressed="${activeFilter === filter.id}"
      title="${t('eventPanel.filterTitle', { filter: getFilterLabel(filter.id) })}"
    >
      ${icon(filter.iconName, 13)}
      <span class="event-filter-label">${t(`eventPanel.filters.${filter.id}`)}</span>
      <span class="event-filter-count">${formatNumber(getFilterCount(events, filter.id))}</span>
    </button>
  `).join('');
  panel.appendChild(filterBar);

  const list = document.createElement('div');
  list.className = 'event-list';
  panel.appendChild(list);

  function renderList() {
    const sourceEvents = displayEvents || events;
    const filteredEvents = sourceEvents.filter((event) => matchesFilter(event, activeFilter));
    list.innerHTML = '';

    if (countBadge) {
      countBadge.textContent = activeFilter === 'all'
        ? t('eventPanel.count', { count: formatNumber(sourceEvents.length) })
        : t('eventPanel.filteredCount', {
            visible: formatNumber(filteredEvents.length),
            total: formatNumber(sourceEvents.length),
          });
    }

    if (filteredEvents.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'event-filter-empty';
      empty.innerHTML = `
        <div class="empty-state-icon">${icon('filter', 32)}</div>
        <div class="empty-state-title">${t('eventPanel.noMatchTitle')}</div>
        <div class="empty-state-desc">${t('eventPanel.noMatchDesc', { filter: getFilterLabel(activeFilter) })}</div>
      `;
      list.appendChild(empty);
      return;
    }

    filteredEvents.forEach((event, index) => {
      list.appendChild(createEventItem(event, index, panel, onEventClick));
    });
  }

  filterBar.querySelectorAll('[data-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.filter;
      saveFilter(activeFilter);
      filterBar.querySelectorAll('.event-filter-chip').forEach((chip) => {
        const isActive = chip.dataset.filter === activeFilter;
        chip.classList.toggle('active', isActive);
        chip.setAttribute('aria-pressed', String(isActive));
      });
      renderList();
    });
  });

  renderList();
  void translateDisplayEvents();
  return panel;

  async function translateDisplayEvents() {
    if (!language || language === 'en') return;

    const translatableEvents = events.filter((event) => {
      const fallback = applyLocalTranslationFallback(event, language);
      return eventNeedsLocalization(fallback, language);
    });
    if (!translatableEvents.length) return;

    const cachedTranslations = new Map();
    const missing = [];
    translatableEvents.forEach((event) => {
      const key = translationCacheKey(language, event);
      if (translationCache.has(key)) {
        const cached = translationCache.get(key);
        if (!translatedPayloadNeedsLocalization(cached, language)) {
          cachedTranslations.set(eventTranslationId(event), cached);
          return;
        }
        translationCache.delete(key);
      }
      missing.push({
        ...translationRequestForEvent(event),
      });
    });

    const invalidAfterFirstPass = [];
    if (missing.length) {
      try {
        const response = await translateAnalysisEvents(language, missing);
        (response.items || []).forEach((item) => {
          const originalEvent = translatableEvents.find((event) => eventTranslationId(event) === String(item.id));
          if (!originalEvent) return;
          const parsedDetails = parseTranslatedDetailBlocks(item.description || originalEvent.description || '');
          const translated = {
            summary: item.summary || originalEvent.summary || '',
            description: parsedDetails.description || originalEvent.description || '',
            frame_observation: parsedDetails.frame_observation || originalEvent.frame_observation || '',
            temporal_assessment: parsedDetails.temporal_assessment || originalEvent.temporal_assessment || '',
            anomaly_rationale: parsedDetails.anomaly_rationale || originalEvent.anomaly_rationale || '',
            changes_detected: parsedDetails.changes_detected.length
              ? parsedDetails.changes_detected
              : normalizeList(originalEvent.changes_detected),
          };
          if (!cacheTranslatedEvent(originalEvent, translated, language, cachedTranslations)) {
            invalidAfterFirstPass.push(originalEvent);
          }
        });
      } catch (error) {
        console.debug('Event translation unavailable:', error);
        translatableEvents
          .filter((event) => missing.some((item) => String(item.id) === eventTranslationId(event)))
          .forEach((event) => cacheFallbackEvent(event, language, cachedTranslations));
      }
    }

    if (invalidAfterFirstPass.length) {
      try {
        const retryItems = invalidAfterFirstPass.map(translationRequestForEvent);
        const retryResponse = await translateAnalysisEvents(language, retryItems);
        const resolvedIds = new Set();
        (retryResponse.items || []).forEach((item) => {
          const originalEvent = invalidAfterFirstPass.find((event) => eventTranslationId(event) === String(item.id));
          if (!originalEvent) return;
          const parsedDetails = parseTranslatedDetailBlocks(item.description || originalEvent.description || '');
          const translated = {
            summary: item.summary || originalEvent.summary || '',
            description: parsedDetails.description || originalEvent.description || '',
            frame_observation: parsedDetails.frame_observation || originalEvent.frame_observation || '',
            temporal_assessment: parsedDetails.temporal_assessment || originalEvent.temporal_assessment || '',
            anomaly_rationale: parsedDetails.anomaly_rationale || originalEvent.anomaly_rationale || '',
            changes_detected: parsedDetails.changes_detected.length
              ? parsedDetails.changes_detected
              : normalizeList(originalEvent.changes_detected),
          };
          if (cacheTranslatedEvent(originalEvent, translated, language, cachedTranslations)) {
            resolvedIds.add(eventTranslationId(originalEvent));
          }
        });
        invalidAfterFirstPass
          .filter((event) => !resolvedIds.has(eventTranslationId(event)))
          .forEach((event) => cacheFallbackEvent(event, language, cachedTranslations));
      } catch (error) {
        console.debug('Event translation retry unavailable:', error);
        invalidAfterFirstPass.forEach((event) => cacheFallbackEvent(event, language, cachedTranslations));
      }
    }

    if (!cachedTranslations.size) return;
    displayEvents = events.map((event) => {
      const translated = cachedTranslations.get(eventTranslationId(event));
      return translated
        ? {
            ...event,
            summary: translated.summary,
            description: translated.description,
            frame_observation: translated.frame_observation,
            temporal_assessment: translated.temporal_assessment,
            anomaly_rationale: translated.anomaly_rationale,
            changes_detected: translated.changes_detected,
          }
        : prepareDisplayEvent(event, language);
    });
    renderList();
  }
}

function parseTranslatedDetailBlocks(text) {
  const parsed = {
    description: '',
    frame_observation: '',
    temporal_assessment: '',
    anomaly_rationale: '',
    changes_detected: [],
  };
  const lines = String(text || '').split('\n').map((line) => line.trim()).filter(Boolean);
  const plainLines = [];

  lines.forEach((line) => {
    const block = line.match(/^\[\[(frame_observation|temporal_assessment|anomaly_rationale|change)\]\]\s*(.*)$/);
    if (!block) {
      plainLines.push(line);
      return;
    }
    const [, type, value] = block;
    const cleanValue = value.trim();
    if (!cleanValue) return;
    if (type === 'change') {
      parsed.changes_detected.push(cleanValue);
      return;
    }
    parsed[type] = cleanValue;
  });

  parsed.description = plainLines.join('\n');
  return parsed;
}

export function highlightEvent(eventId) {
  const panel = document.getElementById('event-panel');
  if (!panel) return;

  panel.querySelectorAll('.event-item').forEach((element) => {
    element.classList.remove('active');
  });

  const target = document.getElementById(`event-item-${eventId}`);
  if (target) {
    target.classList.add('active');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
