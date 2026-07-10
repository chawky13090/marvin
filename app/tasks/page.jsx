'use client';
import { useState, useEffect, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { useRouter } from 'next/navigation';

const PRIORITY_CONFIG = {
  urgent: { label: 'Urgent', color: '#ff4757', bg: 'rgba(255,71,87,0.12)', order: 1 },
  high:   { label: 'Haute',  color: '#ff6b35', bg: 'rgba(255,107,53,0.12)', order: 2 },
  medium: { label: 'Moyenne',color: '#ffa502', bg: 'rgba(255,165,2,0.12)',  order: 3 },
  low:    { label: 'Basse',  color: '#2ed573', bg: 'rgba(46,213,115,0.12)', order: 4 },
};

const STATUS_CONFIG = {
  pending:     { label: 'À faire',    color: 'var(--text-secondary)' },
  in_progress: { label: 'En cours',   color: '#ffa502' },
  done:        { label: 'Terminé',    color: '#2ed573' },
  cancelled:   { label: 'Annulé',     color: 'var(--text-secondary)' },
};

const QUICK_ACTIONS = [
  { label: 'Voir mes tâches urgentes', msg: 'Quelles sont mes tâches urgentes ?' },
  { label: 'Ajouter une tâche réunion', msg: 'Ajoute une tâche : Préparer la réunion de demain, priorité haute' },
  { label: 'Résumé des tâches', msg: 'Fais-moi un résumé de toutes mes tâches en cours' },
  { label: 'Tâches du jour', msg: 'Quelles tâches dois-je faire aujourd\'hui ?' },
];

function PriorityBadge({ priority }) {
  const cfg = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.medium;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      padding: '2px 8px', borderRadius: '20px',
      background: cfg.bg, color: cfg.color,
      fontSize: 'var(--font-xs)', fontWeight: 600,
      border: `1px solid ${cfg.color}33`,
    }}>
      {cfg.label}
    </span>
  );
}

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  return (
    <span style={{ fontSize: 'var(--font-xs)', color: cfg.color, fontWeight: 500 }}>
      {cfg.label}
    </span>
  );
}

function TaskRow({ task, onStatusChange, onDelete }) {
  const isDone = task.status === 'done';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '12px',
      padding: '14px 16px',
      background: 'var(--bg-glass)',
      borderRadius: 'var(--radius-md)',
      border: '1px solid var(--border)',
      opacity: isDone ? 0.6 : 1,
      transition: 'all 0.2s ease',
    }}>
      {/* Done toggle */}
      <button
        onClick={() => onStatusChange(task.id, isDone ? 'pending' : 'done')}
        title={isDone ? 'Marquer comme à faire' : 'Marquer comme terminé'}
        style={{
          width: '22px', height: '22px', flexShrink: 0,
          borderRadius: '50%', cursor: 'pointer',
          border: isDone ? '2px solid #2ed573' : '2px solid var(--border)',
          background: isDone ? '#2ed573' : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'white', fontSize: '12px', fontWeight: 700,
          transition: 'all 0.2s ease',
        }}
      >
        {isDone ? '✓' : ''}
      </button>

      {/* Title + meta */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 'var(--font-sm)', fontWeight: 500,
          color: 'var(--text-primary)',
          textDecoration: isDone ? 'line-through' : 'none',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>
          {task.title}
        </div>
        {task.description && (
          <div style={{
            fontSize: 'var(--font-xs)', color: 'var(--text-secondary)',
            marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {task.description}
          </div>
        )}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '4px', flexWrap: 'wrap' }}>
          <PriorityBadge priority={task.priority} />
          <StatusBadge status={task.status} />
          {task.due_date && (
            <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
              Échéance: {new Date(task.due_date).toLocaleDateString('fr-FR')}
            </span>
          )}
          {task.tags && task.tags.length > 0 && task.tags.map(tag => (
            <span key={tag} style={{
              fontSize: 'var(--font-xs)', padding: '1px 6px',
              background: 'var(--bg-secondary)', borderRadius: '10px',
              color: 'var(--text-secondary)', border: '1px solid var(--border)',
            }}>
              {tag}
            </span>
          ))}
        </div>
      </div>

      {/* Status select */}
      <select
        value={task.status}
        onChange={e => onStatusChange(task.id, e.target.value)}
        style={{
          background: 'var(--bg-secondary)', color: 'var(--text-secondary)',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
          padding: '4px 8px', fontSize: 'var(--font-xs)', cursor: 'pointer',
        }}
      >
        <option value="pending">À faire</option>
        <option value="in_progress">En cours</option>
        <option value="done">Terminé</option>
        <option value="cancelled">Annulé</option>
      </select>

      {/* Delete */}
      <button
        onClick={() => onDelete(task.id)}
        title="Supprimer"
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--text-secondary)', fontSize: '16px', padding: '4px',
          borderRadius: 'var(--radius-md)', transition: 'color 0.2s ease',
        }}
        onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
        onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
      >
        ✕
      </button>
    </div>
  );
}

export default function TasksPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newTask, setNewTask] = useState({ title: '', description: '', priority: 'medium', due_date: '' });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const loadTasks = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      const res = await fetch(`/api/tasks?${params}`);
      const data = await res.json();
      setTasks(data.tasks || []);
    } catch (e) {
      setError('Impossible de charger les tâches.');
    } finally {
      setLoading(false);
    }
  }, [filterStatus]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  async function handleStatusChange(id, status) {
    try {
      await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'update', id, status }),
      });
      loadTasks();
    } catch {
      setError('Mise à jour échouée.');
    }
  }

  async function handleDelete(id) {
    if (!confirm('Supprimer cette tâche ?')) return;
    try {
      await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete', id }),
      });
      loadTasks();
    } catch {
      setError('Suppression échouée.');
    }
  }

  async function handleAddTask(e) {
    e.preventDefault();
    if (!newTask.title.trim()) return;
    setSubmitting(true);
    try {
      await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'create',
          title: newTask.title.trim(),
          description: newTask.description.trim(),
          priority: newTask.priority,
          due_date: newTask.due_date || null,
          tags: [],
        }),
      });
      setNewTask({ title: '', description: '', priority: 'medium', due_date: '' });
      setShowAddForm(false);
      loadTasks();
    } catch {
      setError('Création échouée.');
    } finally {
      setSubmitting(false);
    }
  }

  function sendToChat(msg) {
    router.push(`/?q=${encodeURIComponent(msg)}`);
  }

  // Group tasks by priority
  const grouped = {};
  for (const p of ['urgent', 'high', 'medium', 'low']) {
    const list = tasks.filter(t => t.priority === p);
    if (list.length > 0) grouped[p] = list;
  }

  const inputStyle = {
    background: 'var(--bg-secondary)', color: 'var(--text-primary)',
    border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
    padding: '10px 14px', fontSize: 'var(--font-sm)', width: '100%',
    outline: 'none', boxSizing: 'border-box',
  };

  return (
    <div style={{ padding: '24px', maxWidth: '900px', margin: '0 auto' }}>
      {/* Header */}
      <div className="page-header" style={{ marginBottom: '24px' }}>
        <h1 style={{
          fontSize: '24px', fontWeight: 700, margin: 0,
          background: 'var(--accent-gradient)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>
          Tâches
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-sm)', margin: '4px 0 0' }}>
          Gérez vos tâches et priorités
        </p>
      </div>

      {/* Quick Actions */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
        {QUICK_ACTIONS.map(({ label, msg }) => (
          <button key={label} onClick={() => sendToChat(msg)} style={{
            background: 'var(--bg-glass)', border: '1px solid var(--border)',
            borderRadius: '20px', padding: '6px 14px',
            fontSize: 'var(--font-xs)', color: 'var(--text-secondary)',
            cursor: 'pointer', transition: 'all 0.2s ease',
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-primary)'; e.currentTarget.style.color = 'var(--text-primary)'; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap' }}>
        {/* Filter */}
        <div style={{ display: 'flex', gap: '6px' }}>
          {[
            { value: '', label: 'Toutes' },
            { value: 'pending', label: 'À faire' },
            { value: 'in_progress', label: 'En cours' },
            { value: 'done', label: 'Terminées' },
          ].map(({ value, label }) => (
            <button key={value} onClick={() => setFilterStatus(value)} style={{
              padding: '6px 14px', borderRadius: '20px', cursor: 'pointer',
              fontSize: 'var(--font-xs)', fontWeight: filterStatus === value ? 600 : 400,
              border: filterStatus === value ? '1px solid var(--accent-primary)' : '1px solid var(--border)',
              background: filterStatus === value ? 'rgba(var(--accent-rgb, 99,102,241),0.15)' : 'var(--bg-glass)',
              color: filterStatus === value ? 'var(--accent-primary)' : 'var(--text-secondary)',
              transition: 'all 0.2s ease',
            }}>
              {label}
            </button>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        {/* Add button */}
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          style={{
            background: 'var(--accent-gradient)', color: 'white',
            border: 'none', borderRadius: 'var(--radius-md)',
            padding: '8px 18px', fontSize: 'var(--font-sm)', fontWeight: 600,
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px',
          }}
        >
          + Nouvelle tâche
        </button>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          background: 'rgba(255,71,87,0.1)', border: '1px solid rgba(255,71,87,0.3)',
          borderRadius: 'var(--radius-md)', padding: '10px 14px',
          color: '#ff4757', fontSize: 'var(--font-sm)', marginBottom: '16px',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          {error}
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}>✕</button>
        </div>
      )}

      {/* Add Form */}
      {showAddForm && (
        <form onSubmit={handleAddTask} style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)', padding: '20px', marginBottom: '20px',
          display: 'flex', flexDirection: 'column', gap: '14px',
        }}>
          <h3 style={{ margin: 0, fontSize: 'var(--font-base)', color: 'var(--text-primary)' }}>Nouvelle tâche</h3>
          <input
            placeholder="Titre de la tâche *"
            value={newTask.title}
            onChange={e => setNewTask(p => ({ ...p, title: e.target.value }))}
            required
            style={inputStyle}
          />
          <input
            placeholder="Description (optionnel)"
            value={newTask.description}
            onChange={e => setNewTask(p => ({ ...p, description: e.target.value }))}
            style={inputStyle}
          />
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '140px' }}>
              <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>Priorité</label>
              <select value={newTask.priority} onChange={e => setNewTask(p => ({ ...p, priority: e.target.value }))} style={{ ...inputStyle }}>
                <option value="low">Basse</option>
                <option value="medium">Moyenne</option>
                <option value="high">Haute</option>
                <option value="urgent">Urgente</option>
              </select>
            </div>
            <div style={{ flex: 1, minWidth: '140px' }}>
              <label style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>Échéance</label>
              <input
                type="date"
                value={newTask.due_date}
                onChange={e => setNewTask(p => ({ ...p, due_date: e.target.value }))}
                style={{ ...inputStyle, colorScheme: 'dark' }}
              />
            </div>
          </div>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button type="button" onClick={() => setShowAddForm(false)} style={{
              background: 'var(--bg-glass)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)', padding: '8px 16px',
              fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', cursor: 'pointer',
            }}>
              Annuler
            </button>
            <button type="submit" disabled={submitting || !newTask.title.trim()} style={{
              background: 'var(--accent-gradient)', color: 'white',
              border: 'none', borderRadius: 'var(--radius-md)',
              padding: '8px 18px', fontSize: 'var(--font-sm)', fontWeight: 600,
              cursor: submitting ? 'not-allowed' : 'pointer', opacity: submitting ? 0.7 : 1,
            }}>
              {submitting ? 'Création...' : 'Créer'}
            </button>
          </div>
        </form>
      )}

      {/* Task list */}
      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><LoadingRow /></div>
      ) : tasks.length === 0 ? (
        <div style={{
          textAlign: 'center', padding: '60px 20px',
          background: 'var(--bg-glass)', borderRadius: 'var(--radius-md)',
          border: '1px dashed var(--border)',
        }}>
          <div style={{ fontSize: '40px', marginBottom: '12px' }}>✅</div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 'var(--font-sm)' }}>
            {filterStatus ? 'Aucune tâche avec ce filtre.' : 'Aucune tâche. Créez-en une !'}
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {Object.entries(grouped).map(([priority, list]) => (
            <div key={priority}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px',
              }}>
                <span style={{
                  fontSize: 'var(--font-xs)', fontWeight: 700, textTransform: 'uppercase',
                  letterSpacing: '0.06em', color: PRIORITY_CONFIG[priority].color,
                }}>
                  {PRIORITY_CONFIG[priority].label}
                </span>
                <div style={{ flex: 1, height: '1px', background: 'var(--border)' }} />
                <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
                  {list.length} tâche{list.length > 1 ? 's' : ''}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {list.map(task => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    onStatusChange={handleStatusChange}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
