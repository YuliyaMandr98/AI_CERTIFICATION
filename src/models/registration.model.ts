// Минимальная заглушка: реальный src/models/registration.model.ts содержит
// множество enum'ов регистрационного флоу, не нужных этому spec-файлу.
// base-api.service.ts использует только форму ошибки ниже.
export interface ApiError {
  message?: string;
  error_code?: string;
}
