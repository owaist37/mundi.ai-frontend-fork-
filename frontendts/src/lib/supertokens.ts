// Copyright Bunting Labs, Inc. 2025

import SuperTokens from 'supertokens-auth-react';
import EmailPassword from 'supertokens-auth-react/recipe/emailpassword';
import EmailVerification from 'supertokens-auth-react/recipe/emailverification';
import Session from 'supertokens-auth-react/recipe/session';
import { loadSupertokensOnHandleEvent } from './ee-loader';

const websiteDomain = import.meta.env.VITE_WEBSITE_DOMAIN;
if (!websiteDomain) {
  throw new Error('VITE_WEBSITE_DOMAIN is not defined. Please set it in your .env file or build environment.');
}

const emailVerificationMode = import.meta.env.VITE_EMAIL_VERIFICATION;
if (emailVerificationMode !== 'require' && emailVerificationMode !== 'disable') {
  throw new Error("VITE_EMAIL_VERIFICATION must be either 'require' or 'disable'");
}
const emailVerificationEnabled = emailVerificationMode === 'require';

export default async function initSupertokens() {
  const onHandleEvent = await loadSupertokensOnHandleEvent();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recipeList: any[] = [EmailPassword.init({ onHandleEvent }), Session.init({ onHandleEvent })];
  if (emailVerificationEnabled) {
    recipeList.push(
      EmailVerification.init({
        mode: 'REQUIRED',
        onHandleEvent,
      }),
    );
  }

  SuperTokens.init({
    appInfo: {
      appName: 'Mundi',
      apiDomain: websiteDomain,
      websiteDomain: websiteDomain,
      apiBasePath: '/supertokens',
      websiteBasePath: '/auth',
    },
    recipeList,
    style: `
    [data-supertokens~="container"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }`,
  });
}
