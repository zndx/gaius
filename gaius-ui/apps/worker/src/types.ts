/**
 * Shared type definitions for the Gaius web worker.
 *
 * Used by landing page, collection pages, and API routes.
 */

export interface Card {
  card_id: string;
  collection_id: string;
  title: string;
  summary: string;
  image_url?: string;
  source_url: string;
  source_type: string;
  published_at: string;
  source_date?: string;
  sequence?: number;
}

export interface ThemeConfig {
  theme_id: string;
  title?: string;
  subtitle?: string;
}

export interface CollectionSummary {
  text: string;
  model_label: string;
  generated_at: string;
}

export interface CollectionData {
  collection_id: string;
  slug: string;
  name: string;
  description: string;
  summaries: {
    frontier?: CollectionSummary;
    open_weights?: CollectionSummary;
  };
  zettle_aliases: string[];
  cards: Card[];
  updated_at: string;
}

export interface CollectionIndexEntry {
  collection_id: string;
  slug: string;
  name: string;
  description: string;
  featured: boolean;
  published_cards: number;
  total_cards: number;
  last_published_at: string | null;
  updated_at: string | null;
}

export interface CollectionAliasData {
  collection_id: string;
}
