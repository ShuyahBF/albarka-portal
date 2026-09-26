"""forms_core — module commun de gestion de formulaires (création, envoi,
réponses, statistiques).

SOURCE UNIQUE : ce dossier est maintenu dans le dépôt ShuyahBF/Claude
(`forms-core/backend/forms_core/`) et COPIÉ À L'IDENTIQUE dans chaque site
par `forms-core/sync.sh`. Ne jamais le modifier directement dans un site :
corriger ici, monter la version, puis resynchroniser (voir forms-core/README.md).

Contenu :
  - fields     : catalogue des types de champs, normalisation d'un formulaire
  - validation : contrôle d'une réponse côté serveur (obligatoires, formats, conditions)
  - stats      : indicateurs et statistiques par question
  - export     : export CSV lisible dans Excel
  - api        : routes HTTP communes, branchées sur un ADAPTATEUR fourni par
                 le site (base Mongo, droits, destinataires, envois, fichiers)
"""
from .fields import (  # noqa: F401
    DEFAULT_SETTINGS, FIELD_TYPES, field_catalog, normalize_pages, normalize_settings,
    public_definition, value_fields,
)
from .validation import is_visible, validate_submission  # noqa: F401
from .stats import form_stats, in_period, invitation_stats, question_stats  # noqa: F401
from .export import readable_value, submissions_rows, to_csv  # noqa: F401
from .api import FormsAdapter, create_routers, ensure_indexes, new_token, now_iso  # noqa: F401

__version__ = "1.0.0"   # garder identique au fichier forms-core/VERSION
