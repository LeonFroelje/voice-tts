{
  description = "Python devShells";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    nixvim = {
      url = "github:nix-community/nixvim";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixvimModules = {
      url = "github:LeonFroelje/nixvim-modules";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      nixvim,
      nixvimModules,
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3;

      # --- Dependency List ---
      apiDependencies = with python.pkgs; [
        pydantic
        boto3
        aiomqtt
        pydantic-settings
        python-dotenv
        pkgs.piper-tts
      ];

    in
    {
      packages.${system} = {
        default = python.pkgs.buildPythonApplication {
          pname = "voice-tts";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          propagatedBuildInputs = apiDependencies;

          # # Ensure FFmpeg is available to the application at runtime for MP3 conversion
          # nativeBuildInputs = [ pkgs.makeWrapper ];
          # postInstall = ''
          #   wrapProgram $out/bin/voice_tts \
          #     --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg_7-headless ]}
          # '';
        };
      };

      nixosModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.services.voiceTts;
          defaultPkg = self.packages.${pkgs.system}.default;
        in
        {
          options.services.voiceTts = with lib; {
            enable = mkEnableOption "Piper TTS MQTT Worker";

            package = mkOption {
              type = types.package;
              default = defaultPkg;
              description = "The Piper TTS package to use.";
            };

            environmentFile = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = ''
                Path to an environment file for secrets/overrides.
                To prevent leaks, this file should contain:
                - PIPER_S3_SECRET_KEY
              '';
            };

            # --- MQTT Connection ---
            mqttHost = mkOption {
              type = types.str;
              default = "localhost";
              description = "Mosquitto broker IP/Hostname";
            };

            mqttPort = mkOption {
              type = types.int;
              default = 1883;
              description = "Mosquitto broker port";
            };

            # --- Object Storage (S3 Compatible) ---
            s3Endpoint = mkOption {
              type = types.str;
              default = "http://localhost:3900";
              description = "URL to S3 storage";
            };

            s3AccessKey = mkOption {
              type = types.str;
              default = "your-access-key";
              description = "S3 Access Key";
            };

            s3Bucket = mkOption {
              type = types.str;
              default = "voice-commands";
              description = "S3 Bucket Name";
            };

            # --- Piper Models ---
            modelsDir = mkOption {
              type = types.str;
              default = "/var/lib/voiceTts-models";
              description = "Directory to store downloaded Piper ONNX models.";
            };

            defaultVoice = mkOption {
              type = types.str;
              default = "de_DE-thorsten-high";
              description = "The default Piper voice model to use and preload.";
            };

            # --- System ---
            logLevel = mkOption {
              type = types.str;
              default = "INFO";
              description = "Logging Level (DEBUG, INFO, ERROR)";
            };
          };

          config = lib.mkIf cfg.enable {
            systemd.services.voiceTts = {
              description = "Piper TTS MQTT Worker Service";
              wantedBy = [ "multi-user.target" ];
              after = [ "network.target" ];

              environment =
                let
                  env = {
                    PIPER_MQTT_HOST = cfg.mqttHost;
                    PIPER_MQTT_PORT = toString cfg.mqttPort;

                    PIPER_S3_ENDPOINT = cfg.s3Endpoint;
                    PIPER_S3_ACCESS_KEY = cfg.s3AccessKey;
                    PIPER_S3_BUCKET = cfg.s3Bucket;

                    PIPER_MODELS_DIR = cfg.modelsDir;
                    PIPER_DEFAULT_VOICE = cfg.defaultVoice;

                    PIPER_LOG_LEVEL = cfg.logLevel;

                    PYTHONUNBUFFERED = "1";
                  };
                in
                lib.filterAttrs (n: v: v != null) env;

              serviceConfig = {
                # Update this if your binary name changed in pyproject.toml during the refactor!
                ExecStart = "${cfg.package}/bin/voice-tts";
                EnvironmentFile = lib.mkIf (cfg.environmentFile != null) cfg.environmentFile;

                # State Management (Stores the downloaded ONNX voices)
                StateDirectory = "voiceTts-models";

                # Hardening
                DynamicUser = true;
                ProtectSystem = "strict";
                ProtectHome = true;
                PrivateTmp = true;
              };
            };
          };
        };

      devShells.${system} = {
        default =
          (pkgs.buildFHSEnv {
            name = "Python dev shell";
            targetPkgs =
              p: with p; [
                fd
                ripgrep
                (nixvimModules.lib.mkNvim [ nixvimModules.nixosModules.python ])
                python314
                python314Packages.pip
                zlib
                glib
              ];
            runScript = "zsh";
          }).env;

        uv =
          (pkgs.buildFHSEnv {
            name = "uv-shell";
            targetPkgs =
              p: with p; [
                uv
                zlib
                glib
                openssl
                stdenv.cc.cc.lib
                (nixvimModules.lib.mkNvim [ nixvimModules.nixosModules.python ])
              ];
            runScript = "zsh";

            multiPkgs = p: [
              p.zlib
              p.openssl
            ];
          }).env;
      };
    };
}
