/**
 * Leagues API Client — Multi-League Tournament Architecture
 * Handles isolated league queries, match lists, points tables, and admin actions.
 */
(function(window) {
  'use strict';

  var LeaguesAPI = {
    /**
     * Fetches all registered tournament leagues.
     */
    getAll: async function() {
      var res = await fetch('/api/leagues');
      return await res.json();
    },

    /**
     * Fetches details of a single league by ID.
     */
    getById: async function(leagueId) {
      var res = await fetch('/api/leagues/' + leagueId);
      return await res.json();
    },

    /**
     * Fetches matches strictly isolated to a specific league.
     * @param {number|string} leagueId 
     * @param {string} [status] Optional filter: 'live' | 'upcoming' | 'completed'
     */
    getMatches: async function(leagueId, status) {
      var url = '/api/leagues/' + leagueId + '/matches';
      if (status) {
        url += '?status=' + encodeURIComponent(status);
      }
      var res = await fetch(url);
      return await res.json();
    },

    /**
     * Fetches the isolated points table and NRR for a specific league.
     * @param {number|string} leagueId 
     */
    getPointsTable: async function(leagueId) {
      var res = await fetch('/api/leagues/' + leagueId + '/points-table');
      return await res.json();
    },

    /**
     * Fetches high-level metrics (total teams, matches, completed, live, upcoming).
     * @param {number|string} leagueId 
     */
    getOverview: async function(leagueId) {
      var res = await fetch('/api/leagues/' + leagueId + '/overview');
      return await res.json();
    },

    /**
     * Fetches team profile, standing, and match history strictly within the league.
     * @param {number|string} leagueId 
     * @param {string} teamName 
     */
    getTeam: async function(leagueId, teamName) {
      var res = await fetch('/api/leagues/' + leagueId + '/teams/' + encodeURIComponent(teamName));
      return await res.json();
    },

    /**
     * Admin: Creates a new league.
     */
    create: async function(data) {
      var res = await fetch('/api/leagues', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    },

    /**
     * Admin: Updates league metadata or active/disabled status.
     */
    update: async function(leagueId, data) {
      var res = await fetch('/api/leagues/' + leagueId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    },

    /**
     * Admin: Deletes a league with all associated matches.
     */
    delete: async function(leagueId) {
      var res = await fetch('/api/leagues/' + leagueId, {
        method: 'DELETE'
      });
      return await res.json();
    }
  };

  window.LeaguesAPI = LeaguesAPI;
})(window);
