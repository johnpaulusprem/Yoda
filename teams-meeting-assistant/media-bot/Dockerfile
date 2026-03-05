# Multi-stage build for C# Media Bot
# NOTE: This bot requires Windows containers for Graph Communications Media SDK
# Use: docker build -t media-bot . (on Windows Docker with Windows containers)

FROM mcr.microsoft.com/dotnet/aspnet:8.0-nanoserver-ltsc2022 AS base
WORKDIR /app
EXPOSE 8080 8445

FROM mcr.microsoft.com/dotnet/sdk:8.0-nanoserver-ltsc2022 AS build
WORKDIR /src
COPY src/MediaBot/MediaBot.csproj .
RUN dotnet restore
COPY src/MediaBot/ .
RUN dotnet publish -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "MediaBot.dll"]
