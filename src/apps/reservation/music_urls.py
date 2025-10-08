from django.urls import path
from apps.reservation.music_views import (
    PlayersListView,
    PlayerPlayView,
    PlayerPauseView,
    PlayerStopView,
    PlayerNextView,
    PlayerPreviousView,
    PlayerVolumeView,
    PlayerQueueView,
    PlayerPlayMediaView,
    MusicSearchView,
    MusicLibraryTracksView,
    MusicSessionCreateView,
    MusicSessionAddParticipantView,
    MusicSessionParticipantsView,
    MusicSessionRemoveParticipantView,
    MusicSessionCloseView,
)

urlpatterns = [
    # Reproductores
    path('players/', PlayersListView.as_view(), name='music-players-list'),
    path('players/<str:player_id>/play/', PlayerPlayView.as_view(), name='music-player-play'),
    path('players/<str:player_id>/pause/', PlayerPauseView.as_view(), name='music-player-pause'),
    path('players/<str:player_id>/stop/', PlayerStopView.as_view(), name='music-player-stop'),
    path('players/<str:player_id>/next/', PlayerNextView.as_view(), name='music-player-next'),
    path('players/<str:player_id>/previous/', PlayerPreviousView.as_view(), name='music-player-previous'),
    path('players/<str:player_id>/volume/', PlayerVolumeView.as_view(), name='music-player-volume'),
    path('players/<str:player_id>/queue/', PlayerQueueView.as_view(), name='music-player-queue'),
    path('players/<str:player_id>/play-media/', PlayerPlayMediaView.as_view(), name='music-player-play-media'),
    
    # Búsqueda y biblioteca
    path('search/', MusicSearchView.as_view(), name='music-search'),
    path('library/tracks/', MusicLibraryTracksView.as_view(), name='music-library-tracks'),
    
    # Sesiones de música
    path('sessions/create/', MusicSessionCreateView.as_view(), name='music-session-create'),
    path('sessions/<str:session_id>/add-participant/', MusicSessionAddParticipantView.as_view(), name='music-session-add-participant'),
    path('sessions/<str:session_id>/participants/', MusicSessionParticipantsView.as_view(), name='music-session-participants'),
    path('sessions/<str:session_id>/participants/<str:participant_id>/', MusicSessionRemoveParticipantView.as_view(), name='music-session-remove-participant'),
    path('sessions/<str:session_id>/close/', MusicSessionCloseView.as_view(), name='music-session-close'),
]
