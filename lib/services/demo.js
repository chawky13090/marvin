// Service de données de démonstration
// Fournit des données simulées réalistes pour tester sans credentials OAuth

const now = new Date();
function daysAgo(n) { const d = new Date(now); d.setDate(d.getDate() - n); return d.toISOString(); }
function daysFromNow(n) { const d = new Date(now); d.setDate(d.getDate() + n); return d.toISOString(); }
function hoursFromNow(n) { const d = new Date(now); d.setHours(d.getHours() + n); return d.toISOString(); }
function setTime(d, h, m) { const dt = new Date(d); dt.setHours(h, m, 0, 0); return dt.toISOString(); }

let nextEmailId = 100;
let nextEventId = 200;

// ── Emails de démonstration ─────────────────────────────

const demoEmails = [
  {
    id: 'demo-1', from: 'Marie Dupont <marie.dupont@entreprise.fr>', to: 'moi',
    subject: 'Réunion de projet - Lundi 10h', date: daysAgo(0),
    body: 'Bonjour,\n\nJe vous confirme la réunion de projet prévue lundi à 10h en salle Confluence.\n\nOrdre du jour :\n1. Point d\'avancement Sprint 12\n2. Revue des KPIs\n3. Planification Sprint 13\n\nMerci de préparer vos retours.\n\nCordialement,\nMarie Dupont',
    read: false, labels: ['travail', 'important'],
  },
  {
    id: 'demo-2', from: 'Pierre Martin <p.martin@client.com>', to: 'moi',
    subject: 'Demande de devis - Projet digitalisation', date: daysAgo(0),
    body: 'Bonjour,\n\nSuite à notre échange téléphonique, je souhaiterais recevoir un devis pour le projet de digitalisation de nos processus internes.\n\nLe périmètre comprend :\n- Audit des processus existants\n- Mise en place d\'un outil de gestion documentaire\n- Formation des équipes\n\nDélai souhaité : 3 mois\n\nDans l\'attente de votre retour,\nPierre Martin\nDirecteur des Opérations',
    read: false, labels: ['client', 'urgent'],
  },
  {
    id: 'demo-3', from: 'Sophie Bernard <sophie.b@rh.entreprise.fr>', to: 'moi',
    subject: 'Congés été 2026 - Validation', date: daysAgo(1),
    body: 'Bonjour,\n\nVotre demande de congés du 14 au 25 juillet a été validée par votre responsable.\n\nN\'oubliez pas de mettre à jour votre message d\'absence automatique.\n\nBonne journée,\nSophie Bernard\nService RH',
    read: true, labels: ['rh'],
  },
  {
    id: 'demo-4', from: 'Newsletter Tech <news@techdigest.fr>', to: 'moi',
    subject: 'Les 10 tendances IA à suivre en 2026', date: daysAgo(1),
    body: 'Découvrez les dernières tendances en intelligence artificielle :\n\n1. Agents IA autonomes\n2. RAG avancé\n3. LLM multimodaux\n4. IA générative pour l\'entreprise\n5. Sécurité et IA\n...\n\nLire la suite sur techdigest.fr',
    read: true, labels: ['newsletter'],
  },
  {
    id: 'demo-5', from: 'Jean-Luc Moreau <jl.moreau@fournisseur.fr>', to: 'moi',
    subject: 'RE: Facture #2024-0892 - Paiement en attente', date: daysAgo(2),
    body: 'Bonjour,\n\nJe me permets de revenir vers vous concernant la facture #2024-0892 d\'un montant de 3 450€ HT, dont l\'échéance était le 15 mai.\n\nPourriez-vous vérifier l\'état du règlement ?\n\nMerci d\'avance,\nJean-Luc Moreau',
    read: false, labels: ['comptabilité', 'urgent'],
  },
  {
    id: 'demo-6', from: 'Claire Lefèvre <claire@equipe.fr>', to: 'moi',
    subject: 'Compte-rendu réunion client ABC Corp', date: daysAgo(2),
    body: 'Salut,\n\nVoici le CR de la réunion avec ABC Corp :\n\n- Ils sont satisfaits de la V2\n- Demande d\'ajout d\'un module reporting\n- Prochaine livraison prévue fin juin\n- Budget additionnel : 15K€\n\nJe t\'envoie le document détaillé demain.\n\nClaire',
    read: true, labels: ['travail'],
  },
  {
    id: 'demo-7', from: 'Support IT <support@entreprise.fr>', to: 'moi',
    subject: 'Maintenance serveurs - Samedi 24 mai', date: daysAgo(3),
    body: 'Chers collaborateurs,\n\nUne maintenance préventive des serveurs est prévue samedi 24 mai de 6h à 12h.\n\nServices impactés :\n- Messagerie\n- Drive partagé\n- Intranet\n\nMerci de votre compréhension.\nL\'équipe IT',
    read: true, labels: ['it'],
  },
  {
    id: 'demo-8', from: 'Thomas Petit <thomas@partenaire.fr>', to: 'moi',
    subject: 'Invitation - Afterwork vendredi', date: daysAgo(3),
    body: 'Hello !\n\nOn organise un afterwork vendredi soir au Café des Arts à partir de 18h30.\n\nTu es des nôtres ? 🍻\n\nThomas',
    read: true, labels: ['perso'],
  },
  {
    id: 'demo-9', from: 'Banque Digitale <notifications@mabanque.fr>', to: 'moi',
    subject: 'Virement reçu - 2 800,00 €', date: daysAgo(4),
    body: 'Bonjour,\n\nUn virement de 2 800,00 € a été crédité sur votre compte.\n\nLibellé : SALAIRE MAI 2026\nDate de valeur : 20/05/2026\n\nCordialement,\nVotre banque en ligne',
    read: true, labels: ['banque'],
  },
  {
    id: 'demo-10', from: 'Amélie Roux <a.roux@marketing.fr>', to: 'moi',
    subject: 'Validation visuel campagne été', date: daysAgo(5),
    body: 'Bonjour,\n\nPouvez-vous valider le visuel de la campagne été ci-joint ?\n\nDélai : mercredi au plus tard pour l\'envoi en impression.\n\nMerci !\nAmélie',
    read: false, labels: ['marketing', 'urgent'],
  },
];

// ── Événements de démonstration ─────────────────────────

const demoEvents = [
  {
    id: 'evt-1', title: 'Réunion d\'équipe hebdomadaire',
    start: setTime(daysFromNow(0), 10, 0), end: setTime(daysFromNow(0), 11, 0),
    description: 'Point d\'avancement avec l\'équipe projet', location: 'Salle Confluence',
    color: '#8B5CF6',
  },
  {
    id: 'evt-2', title: 'Déjeuner client - ABC Corp',
    start: setTime(daysFromNow(0), 12, 30), end: setTime(daysFromNow(0), 14, 0),
    description: 'Déjeuner d\'affaires avec M. Durand', location: 'Restaurant Le Comptoir',
    color: '#3B82F6',
  },
  {
    id: 'evt-3', title: 'Call avec Pierre Martin',
    start: setTime(daysFromNow(1), 9, 30), end: setTime(daysFromNow(1), 10, 0),
    description: 'Discussion devis projet digitalisation', location: 'Teams',
    color: '#10B981',
  },
  {
    id: 'evt-4', title: 'Présentation trimestrielle',
    start: setTime(daysFromNow(1), 14, 0), end: setTime(daysFromNow(1), 16, 0),
    description: 'Résultats Q2 - Direction générale', location: 'Salle du Board',
    color: '#F59E0B',
  },
  {
    id: 'evt-5', title: 'Formation sécurité IT',
    start: setTime(daysFromNow(2), 9, 0), end: setTime(daysFromNow(2), 12, 0),
    description: 'Formation obligatoire cybersécurité', location: 'Salle Formation B',
    color: '#EF4444',
  },
  {
    id: 'evt-6', title: 'Entretien candidat - Dev Senior',
    start: setTime(daysFromNow(3), 11, 0), end: setTime(daysFromNow(3), 12, 0),
    description: 'Entretien technique candidat poste développeur', location: 'Bureau 204',
    color: '#8B5CF6',
  },
  {
    id: 'evt-7', title: 'Afterwork équipe',
    start: setTime(daysFromNow(4), 18, 30), end: setTime(daysFromNow(4), 21, 0),
    description: 'Afterwork mensuel', location: 'Café des Arts',
    color: '#EC4899',
  },
  {
    id: 'evt-8', title: 'Revue de code',
    start: setTime(daysFromNow(1), 16, 30), end: setTime(daysFromNow(1), 17, 30),
    description: 'Review PR #342 et #345', location: 'Salle Dev',
    color: '#6366F1',
  },
  {
    id: 'evt-9', title: 'Rendez-vous médecin',
    start: setTime(daysFromNow(5), 8, 30), end: setTime(daysFromNow(5), 9, 30),
    description: 'Visite annuelle', location: 'Cabinet Dr. Lambert',
    color: '#14B8A6',
  },
  {
    id: 'evt-10', title: 'Sprint Planning',
    start: setTime(daysFromNow(7), 9, 0), end: setTime(daysFromNow(7), 11, 0),
    description: 'Planification Sprint 14', location: 'Salle Confluence',
    color: '#8B5CF6',
  },
];

// ── API de démonstration ────────────────────────────────

export function getDemoEmails(count = 10) {
  return demoEmails.slice(0, count);
}

export function getDemoEmail(emailId) {
  return demoEmails.find(e => e.id === emailId) || null;
}

export function searchDemoEmails(query) {
  const q = query.toLowerCase();
  return demoEmails.filter(e =>
    e.subject.toLowerCase().includes(q) ||
    e.from.toLowerCase().includes(q) ||
    e.body.toLowerCase().includes(q)
  );
}

export async function sendDemoEmail(to, subject, body) {
  await new Promise(r => setTimeout(r, 500));
  return { success: true, messageId: `demo-sent-${++nextEmailId}`, to, subject };
}

export async function replyDemoEmail(emailId, body) {
  const original = getDemoEmail(emailId);
  await new Promise(r => setTimeout(r, 500));
  return { success: true, messageId: `demo-reply-${++nextEmailId}`, inReplyTo: emailId, originalSubject: original?.subject };
}

export async function draftDemoEmail(to, subject, body) {
  await new Promise(r => setTimeout(r, 300));
  return { success: true, draftId: `demo-draft-${++nextEmailId}`, to, subject };
}

export function getDemoEvents(startDate, endDate) {
  const start = new Date(startDate || daysAgo(7));
  const end = new Date(endDate || daysFromNow(30));
  return demoEvents.filter(e => {
    const eventStart = new Date(e.start);
    return eventStart >= start && eventStart <= end;
  });
}

export function getDemoEvent(eventId) {
  return demoEvents.find(e => e.id === eventId) || null;
}

export async function createDemoEvent(title, startDate, endDate, description, location) {
  const newEvent = {
    id: `evt-${++nextEventId}`,
    title, start: startDate, end: endDate,
    description: description || '', location: location || '',
    color: '#8B5CF6',
  };
  demoEvents.push(newEvent);
  await new Promise(r => setTimeout(r, 400));
  return { success: true, event: newEvent };
}

export async function updateDemoEvent(eventId, updates) {
  const event = demoEvents.find(e => e.id === eventId);
  if (!event) return { success: false, error: 'Événement non trouvé' };
  Object.assign(event, updates);
  await new Promise(r => setTimeout(r, 300));
  return { success: true, event };
}

export async function deleteDemoEvent(eventId) {
  const idx = demoEvents.findIndex(e => e.id === eventId);
  if (idx === -1) return { success: false, error: 'Événement non trouvé' };
  demoEvents.splice(idx, 1);
  await new Promise(r => setTimeout(r, 300));
  return { success: true };
}

export function checkDemoAvailability(date) {
  const targetDate = new Date(date);
  const dayEvents = demoEvents.filter(e => {
    const eDate = new Date(e.start);
    return eDate.toDateString() === targetDate.toDateString();
  });

  const slots = [];
  const hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17];
  for (const h of hours) {
    const busy = dayEvents.some(e => {
      const s = new Date(e.start).getHours();
      const en = new Date(e.end).getHours();
      return h >= s && h < en;
    });
    if (!busy) {
      slots.push({ start: `${h}:00`, end: `${h + 1}:00`, available: true });
    }
  }
  return { date: targetDate.toDateString(), freeSlots: slots, busyCount: dayEvents.length };
}
