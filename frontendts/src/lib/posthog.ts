import posthog from 'posthog-js';

export const initPostHog = () => {
  const apiKey = import.meta.env.VITE_POSTHOG_API_KEY;

  if (apiKey) {
    posthog.init(apiKey, {
      api_host: 'https://us.i.posthog.com',
      defaults: '2025-05-24',
    });
    return true;
  }

  return false;
};

export { posthog };
