{{- define "eidolon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "eidolon.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "eidolon.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "eidolon.labels" -}}
app.kubernetes.io/name: {{ include "eidolon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "eidolon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "eidolon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "eidolon.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "eidolon.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "eidolon.postgresName" -}}
{{- printf "%s-postgres" (include "eidolon.fullname" .) -}}
{{- end -}}

{{/* The database URL: bundled Postgres, or the external one. */}}
{{- define "eidolon.databaseUrl" -}}
{{- if .Values.postgres.enabled -}}
postgresql+psycopg://eidolon:$(EIDOLON_DB_PASSWORD)@{{ include "eidolon.postgresName" . }}:5432/eidolon
{{- else -}}
{{ required "externalDatabase.url is required when postgres.enabled=false" .Values.externalDatabase.url }}
{{- end -}}
{{- end -}}
