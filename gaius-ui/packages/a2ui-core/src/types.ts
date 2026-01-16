/**
 * A2UI Message Types
 *
 * Simplified A2UI types for the initial Gaius implementation.
 * Full A2UI spec: https://github.com/google/A2UI
 */

import { z } from 'zod';

// Component types supported in our catalog
export type ComponentType =
  | 'Text'
  | 'Button'
  | 'Container'
  | 'GaiusShell'
  | 'GaiusAuthResult';

// Base component definition
export interface A2UIComponent {
  id: string;
  component: {
    [K in ComponentType]?: Record<string, unknown>;
  };
}

// Surface update message
export interface SurfaceUpdate {
  surfaceId: string;
  components: A2UIComponent[];
}

// A2UI message envelope
export interface A2UIMessage {
  surfaceUpdate?: SurfaceUpdate;
  dataModelUpdate?: {
    path: string;
    value: unknown;
  };
  beginRendering?: boolean;
  endRendering?: boolean;
}

// Zod schemas for validation
export const ComponentSchema = z.object({
  id: z.string(),
  component: z.record(z.record(z.unknown())),
});

export const SurfaceUpdateSchema = z.object({
  surfaceId: z.string(),
  components: z.array(ComponentSchema),
});

export const A2UIMessageSchema = z.object({
  surfaceUpdate: SurfaceUpdateSchema.optional(),
  dataModelUpdate: z
    .object({
      path: z.string(),
      value: z.unknown(),
    })
    .optional(),
  beginRendering: z.boolean().optional(),
  endRendering: z.boolean().optional(),
});

// Helper to create component definitions
export function createComponent<T extends ComponentType>(
  id: string,
  type: T,
  props: Record<string, unknown>
): A2UIComponent {
  return {
    id,
    component: {
      [type]: props,
    },
  };
}

// OAuth callback specific types
export interface OAuthCallbackData {
  code?: string;
  state?: string;
  error?: string;
  errorDescription?: string;
}

// Generate A2UI message for OAuth result
export function createOAuthResultMessage(
  data: OAuthCallbackData,
  callbackSucceeded: boolean = false
): A2UIMessage {
  const components: A2UIComponent[] = [];

  if (data.code) {
    components.push(
      createComponent('auth-result', 'GaiusAuthResult', {
        success: true,
        code: data.code,
        state: data.state,
        callbackSucceeded,
      })
    );
  } else {
    components.push(
      createComponent('auth-result', 'GaiusAuthResult', {
        success: false,
        error: data.error || 'unknown_error',
        errorDescription: data.errorDescription || 'Authorization failed',
        callbackSucceeded: false,
      })
    );
  }

  return {
    surfaceUpdate: {
      surfaceId: 'main',
      components: [
        createComponent('shell', 'GaiusShell', {
          title: data.code ? 'Authorization Successful' : 'Authorization Failed',
        }),
        ...components,
      ],
    },
  };
}
