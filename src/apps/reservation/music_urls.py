from django.urls import path
from apps.reservation.music_views import (
    PlayersListView,
    PlayerPlayView,
    PlayerPauseView,
    PlayerStopView,
    PlayerNextView,
    PlayerPreviousView,
    PlayerVolumeView,
    PlayerPowerView,
    AutoPowerOnView,
    AutoPowerOnAllView,
    MusicAssistantHealthView,
    PlayerQueueView,
    PlayerClearQueueView,
    PlayerPlayMediaView,
    MusicSearchView,
    MusicLibraryTracksView,
    RequestAccessView,
    PendingRequestsView,
    AcceptRequestView,
    RejectRequestView,
    ParticipantsView,
    RemoveParticipantView,
)

urlpatterns = [
    # Monitoreo
    path('health/', MusicAssistantHealthView.as_view(), name='music-health'),
    
    # Utilidades
    path('auto-power-on/', AutoPowerOnView.as_view(), name='music-auto-power-on'),
    path('auto-power-on-all/', AutoPowerOnAllView.as_view(), name='music-auto-power-on-all'),
    
    # Reproductores
    path('players/', PlayersListView.as_view(), name='music-players-list'),
    path('players/<str:player_id>/play/', PlayerPlayView.as_view(), name='music-player-play'),
    path('players/<str:player_id>/pause/', PlayerPauseView.as_view(), name='music-player-pause'),
    path('players/<str:player_id>/stop/', PlayerStopView.as_view(), name='music-player-stop'),
    path('players/<str:player_id>/next/', PlayerNextView.as_view(), name='music-player-next'),
    path('players/<str:player_id>/previous/', PlayerPreviousView.as_view(), name='music-player-previous'),
    path('players/<str:player_id>/volume/', PlayerVolumeView.as_view(), name='music-player-volume'),
    path('players/<str:player_id>/power/', PlayerPowerView.as_view(), name='music-player-power'),
    path('players/<str:player_id>/queue/', PlayerQueueView.as_view(), name='music-player-queue'),
    path('players/<str:player_id>/clear-queue/', PlayerClearQueueView.as_view(), name='music-player-clear-queue'),
    path('players/<str:player_id>/play-media/', PlayerPlayMediaView.as_view(), name='music-player-play-media'),
    
    # Búsqueda y biblioteca
    path('search/', MusicSearchView.as_view(), name='music-search'),
    path('library/tracks/', MusicLibraryTracksView.as_view(), name='music-library-tracks'),
    
    # Gestión de acceso a sesiones (basadas en reservation_id)
    path('sessions/<str:reservation_id>/request-access/', RequestAccessView.as_view(), name='music-request-access'),
    path('sessions/<str:reservation_id>/requests/', PendingRequestsView.as_view(), name='music-pending-requests'),
    path('sessions/<str:reservation_id>/requests/<str:request_id>/accept/', AcceptRequestView.as_view(), name='music-accept-request'),
    path('sessions/<str:reservation_id>/requests/<str:request_id>/reject/', RejectRequestView.as_view(), name='music-reject-request'),
    path('sessions/<str:reservation_id>/participants/', ParticipantsView.as_view(), name='music-participants'),
    path('sessions/<str:reservation_id>/participants/<str:participant_id>/', RemoveParticipantView.as_view(), name='music-remove-participant'),
]
