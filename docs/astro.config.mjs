// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://docs.mundi.ai',
	integrations: [
		starlight({
			title: 'Mundi GIS Documentation',
			logo: {
				light: './src/assets/Mundi-light.svg',
				dark: './src/assets/Mundi-dark.svg',
				replacesTitle: true,
			},
			favicon: '/favicon-light.svg',
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/BuntingLabs/mundi.ai' }],
			sidebar: [
				{
					label: 'Introduction',
					slug: 'index',
				},
				{
					label: 'Getting started',
					items: [
						{ label: 'Making your first map', slug: 'getting-started/making-your-first-map' },
					],
				},
				{
					label: 'Guides',
					items: [
						{ label: 'Connecting to PostGIS', slug: 'guides/connecting-to-postgis' },
						{ label: 'Self-hosting Mundi', slug: 'guides/self-hosting-mundi' },
					],
				},
			],
			// Set English as the default language for this site.
			defaultLocale: 'root',
			locales: {
				// English docs in `src/content/docs/` (root)
				root: {
					label: 'English',
					lang: 'en',
				},
			},

		}),
	],
});
