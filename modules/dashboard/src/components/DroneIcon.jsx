import React from 'react';

/**
 * Tactical Drone Icon adapted from Drone Swarm Search Environment (DSSE)
 */
export default function DroneIcon({ className = 'w-4 h-4', 'aria-hidden': ariaHidden = true }) {
  return (
    <svg
      viewBox="80 100 240 105"
      className={className}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden={ariaHidden}
    >
      <path
        d="m305.39 132a8.81 8.81 0 0 1 -8.84 8.84h-54.55l-4 11.6a17.9 17.9 0 0 1 -16.91 12h-42.18a17.89 17.89 0 0 1 -16.89-12l-4.02-11.64h-54.57a8.84 8.84 0 1 1 0-17.67h43.25c8.72-9.5 29.31-21.41 53.32-21.41s44.6 11.91 53.32 21.41h43.23a8.83 8.83 0 0 1 8.84 8.87z"
        fill="currentColor"
        fillOpacity="0.85"
      />
      <path
        d="m221.07 165.44h-42.16a18.9 18.9 0 0 1 -17.83-12.67l-3.84-11h-53.81a9.84 9.84 0 0 1 0-19.67h42.81c9.75-10.38 30.58-21.41 53.76-21.41s44 11 53.76 21.41h42.79a9.84 9.84 0 0 1 9.84 9.83 9.83 9.83 0 0 1 -9.84 9.84h-53.81l-3.82 11a18.91 18.91 0 0 1 -17.85 12.67zm-117.64-41.31a7.82 7.82 0 0 0 -7.82 7.87 7.84 7.84 0 0 0 7.82 7.84h54.57a1 1 0 0 1 1 .67l4 11.6a16.92 16.92 0 0 0 15.95 11.33h42.16a16.93 16.93 0 0 0 16-11.32l4.05-11.65a1 1 0 0 1 .94-.67h54.52a7.83 7.83 0 0 0 5.55-2.3 7.75 7.75 0 0 0 2.29-5.54 7.84 7.84 0 0 0 -7.84-7.83h-43.3a1 1 0 0 1 -.73-.33c-9.34-10.15-29.77-21.08-52.59-21.08s-43.25 10.93-52.59 21.08a1 1 0 0 1 -.73.33z"
        fill="currentColor"
      />
      <rect fill="currentColor" fillOpacity="0.9" height="33.83" rx="4.17" width="18.26" x="92.29" y="113.84" />
      <rect fill="currentColor" fillOpacity="0.9" height="33.83" rx="4.17" width="18.26" x="289.45" y="113.84" />
    </svg>
  );
}
