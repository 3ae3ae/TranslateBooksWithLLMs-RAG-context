import { html, useState } from './html.js';
import { Button } from './core.js';
import { Dialog, toast } from './overlays.js';
import { Field, TextInput, Textarea } from './forms.js';
import { stylesApi } from '../lib/api.js';
import { t } from '../lib/i18n.js';

/** Create a style guide. onSaved(name) after success. */
export function StyleDialog({ onClose, onSaved }) {
  const [name, setName] = useState('');
  const [translation, setTranslation] = useState('');
  const [polish, setPolish] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const valid = name.trim() && (translation.trim() || polish.trim());
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await stylesApi.create({ name: name.trim(), translation, refinement: polish });
      toast({ tone: 'success', title: t('styles.toast.created') });
      onSaved && onSaved((r && r.name) || name.trim());
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return html`<${Dialog}
    title=${t('styles.new_title')}
    desc=${t('styles.new_desc')}
    size="wide"
    onClose=${onClose}
    footer=${html`
      <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
      <${Button} variant="primary" loading=${busy} disabled=${!valid} onClick=${save}>${t('common.create')}<//>`}
  >
    <div class="form-rows">
      <${Field} label=${t('styles.field.name')} htmlFor="style-name" error=${error}>
        <${TextInput} id="style-name" value=${name} onInput=${setName} placeholder=${t('styles.field.name_placeholder')} data-autofocus />
      <//>
      <${Field} label=${t('styles.field.translation')} htmlFor="style-translation" help=${t('styles.field.translation_help')}>
        <${Textarea} id="style-translation" rows=${6} value=${translation} onInput=${setTranslation} placeholder=${t('styles.field.translation_placeholder')} />
      <//>
      <${Field} label=${t('styles.field.polish')} htmlFor="style-polish" optional help=${t('styles.field.polish_help')}>
        <${Textarea} id="style-polish" rows=${4} value=${polish} onInput=${setPolish} />
      <//>
    </div>
  <//>`;
}
